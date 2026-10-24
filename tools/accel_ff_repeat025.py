"""Exactly five supervised 0.25-Ka observations, same installed A. FILES ONLY by default."""
import argparse
import json
from pathlib import Path
import statistics
import time
import accel_ff_gain_batch as batch

base=batch.base
TMP=batch.TMP
ROOT_RESTORE=TMP/'accel-gain-restore-1792645768217111300.json'
ORDER=(25,25,25,25,25)


def summarize(runs):
    if any(r['metrics']['gain_percent']!=25 for r in runs):raise ValueError('Mixed gains are not five 0.25 repeats')
    names=set().union(*(r['metrics'].keys() for r in runs)) if runs else set()
    metrics={}
    for k in sorted(names-{'mode','gain_percent'}):
        vals=[r['metrics'][k] for r in runs if isinstance(r['metrics'].get(k),(int,float))]
        metrics[k]=dict(n=len(vals),missing=len(runs)-len(vals),
            mean=statistics.mean(vals) if vals else None,
            sd=statistics.stdev(vals) if len(vals)>1 else None,
            min=min(vals) if vals else None,max=max(vals) if vals else None)
    return dict(completed=len(runs)==5,runs=len(runs),gain_percent=25,metrics=metrics,
        qualification='Five repeated 0.25-Ka observations; no concurrent OFF control. Do not claim a causal improvement using unmatched historical means.')


def execute(path,parent):
    return batch.execute(path,parent,order=ORDER,summary_fn=summarize)


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);m=p.add_mutually_exclusive_group()
    m.add_argument('--prepare-off',action='store_true');m.add_argument('--execute-five',type=Path)
    m.add_argument('--restore-b-drive-off',type=Path)
    p.add_argument('--baseline-restore',type=Path)
    p.add_argument('--drive-off-unlocked-no-load-fixed',action='store_true')
    p.add_argument('--operator-present-whole-batch-drive-on-no-alarm-05a',action='store_true');a=p.parse_args(argv)
    if (a.prepare_off or a.restore_b_drive_off) and not a.drive_off_unlocked_no_load_fixed:p.error('Fresh drive OFF required')
    if a.execute_five and not a.operator_present_whole_batch_drive_on_no_alarm_05a:p.error('Fresh supervised powered confirmation required')
    source=a.execute_five or a.restore_b_drive_off
    selected=a.baseline_restore or (Path(json.loads(source.read_text())['baseline_restore_receipt']) if source else ROOT_RESTORE)
    batch.setup(selected)
    if not (a.prepare_off or source):print('OFFLINE PASS: exact five 0.25-Ka repeats, same image; no devices');return 0
    mode='stage' if a.prepare_off else 'restore' if a.restore_b_drive_off else 'batch'
    name='accel-repeat025-'+mode+'-'+str(time.time_ns())
    row=dict(mode=mode,pass_=False,receipt_path=str(TMP/(name+'.json')),steps=[],commands=[],uart=[],samples=[],
        postflight={},runs=[],attempts=[],image_sha256=batch.SHA,elf_sha256=batch.ELF_SHA,
        baseline_restore_receipt=str(base.BASE_RESTORE_RECEIPT),friction_enabled=True,bemf_enabled=False,
        physical_power_off=a.drive_off_unlocked_no_load_fixed,automatic_retry=False,
        operator_present_whole_batch=a.operator_present_whole_batch_drive_on_no_alarm_05a)
    batch.prior.checkpoint(row,'prepared')
    try:
        if a.prepare_off:
            base.stage(row,name,batch.image());row['batch_order']=list(ORDER);row['batch_runs']=5
        elif a.restore_b_drive_off:base.restore(row,name,source,batch.image())
        else:execute(a.execute_five,row)
    except BaseException as error:
        row['failure']=str(error)
        if row.get('hardware_attempted') and not row.get('final_cpu_halted'):
            try:base.hw.emergency_off(row,TMP/(name+'-failed.bin'))
            except Exception as off:row['cleanup_error']=str(off)
    if mode=='batch':row['summary']=summarize(row['runs'])
    batch.prior.checkpoint(row,'complete' if row['pass_'] else 'stopped')
    print(('PASS: ' if row['pass_'] else 'STOPPED: ')+row['receipt_path'],flush=True)
    if row.get('failure'):print(row['failure'],flush=True)
    return 0 if row['pass_'] else 1


if __name__=='__main__':raise SystemExit(main())
