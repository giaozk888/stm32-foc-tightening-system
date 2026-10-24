"""Exactly six supervised startup timestamp observations, same 0.25-Ka A. Default FILES ONLY."""
import argparse
import json
import statistics
from pathlib import Path
import time
import startup_timestamps_board as board

gain=board.gain
base=board.base
TMP=board.TMP
ROOT_RESTORE=TMP/'startup-times-restore-1792649182262901700.json'
ORDER=(25,25,25,25,25,25)


def describe(values,total):
    vals=[v for v in values if isinstance(v,(int,float))]
    return dict(n=len(vals),missing=total-len(vals),mean=statistics.mean(vals) if vals else None,
        sd=statistics.stdev(vals) if len(vals)>1 else None,min=min(vals) if vals else None,max=max(vals) if vals else None)


def summarize(runs):
    if any(r['metrics']['gain_percent']!=25 for r in runs):raise ValueError('Only six fixed 0.25-Ka observations')
    metrics={};timings={}
    names=set().union(*(r['metrics'].keys() for r in runs)) if runs else set()
    for k in sorted(names-{'mode','gain_percent','startup_delays_ms','startup_log_seq'}):
        metrics[k]=describe([r['metrics'].get(k) for r in runs],len(runs))
    for name in ('t0','t_iq','t_motion','t_speed','t_stable'):
        # Existing owner stores values in ms under startup_delays_ms; its
        # nested historical keys still end in _us. Do not divide twice.
        timings[name+'_ms']=describe([r['metrics'].get('startup_delays_ms',{}).get(name+'_delay_us') for r in runs],len(runs))
    return dict(completed=len(runs)==6,runs=len(runs),gain_percent=25,metrics=metrics,startup_relative_ms=timings,
        qualification='Six fresh same-image observations only; t0=trajectory start, t_stable=confirmation event, legacy START_MS is backdated. No automatic parameter change or historical pooling.')


def execute(path,parent):
    return gain.execute(path,parent,order=ORDER,summary_fn=summarize,metrics_fn=board.classify)


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);m=p.add_mutually_exclusive_group()
    m.add_argument('--prepare-off',action='store_true');m.add_argument('--execute-six',type=Path)
    m.add_argument('--restore-b-drive-off',type=Path);p.add_argument('--baseline-restore',type=Path)
    p.add_argument('--drive-off-unlocked-no-load-fixed',action='store_true')
    p.add_argument('--operator-present-whole-batch-drive-on-no-alarm-05a',action='store_true');a=p.parse_args(argv)
    if (a.prepare_off or a.restore_b_drive_off) and not a.drive_off_unlocked_no_load_fixed:p.error('Fresh drive OFF required')
    if a.execute_six and not a.operator_present_whole_batch_drive_on_no_alarm_05a:p.error('Fresh supervised whole-batch powered confirmation required')
    source=a.execute_six or a.restore_b_drive_off
    selected=a.baseline_restore or (Path(json.loads(source.read_text())['baseline_restore_receipt']) if source else ROOT_RESTORE)
    board.setup(selected)
    if not (a.prepare_off or source):print('OFFLINE PASS: exactly six startup-timestamp repeats, same A/0.25 Ka; no devices');return 0
    mode='stage' if a.prepare_off else 'restore' if a.restore_b_drive_off else 'batch'
    name='startup-repeat-'+mode+'-'+str(time.time_ns())
    row=dict(mode=mode,pass_=False,receipt_path=str(TMP/(name+'.json')),steps=[],commands=[],uart=[],samples=[],
        postflight={},runs=[],attempts=[],image_sha256=board.SHA,elf_sha256=board.ELF_SHA,
        baseline_restore_receipt=str(base.BASE_RESTORE_RECEIPT),friction_enabled=True,bemf_enabled=False,gain_percent=25,
        physical_power_off=a.drive_off_unlocked_no_load_fixed,automatic_retry=False,
        operator_present_whole_batch=a.operator_present_whole_batch_drive_on_no_alarm_05a)
    gain.prior.checkpoint(row,'prepared')
    try:
        if a.prepare_off:
            base.stage(row,name,board.image());row['batch_order']=list(ORDER);row['batch_runs']=6
        elif a.restore_b_drive_off:base.restore(row,name,source,board.image())
        else:execute(a.execute_six,row)
    except BaseException as error:
        row['failure']=str(error)
        if row.get('hardware_attempted') and not row.get('final_cpu_halted'):
            try:base.hw.emergency_off(row,TMP/(name+'-failed.bin'))
            except Exception as off:row['cleanup_error']=str(off)
    if mode=='batch':row['summary']=summarize(row['runs'])
    gain.prior.checkpoint(row,'complete' if row['pass_'] else 'stopped')
    print(('PASS: ' if row['pass_'] else 'STOPPED: ')+row['receipt_path'],flush=True)
    if row.get('failure'):print(row['failure'],flush=True)
    return 0 if row['pass_'] else 1


if __name__=='__main__':raise SystemExit(main())
