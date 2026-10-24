"""Exactly five supervised Ka=0 acquisitions, no gain sweep. FILES ONLY by default."""
import argparse
import json
from pathlib import Path
import statistics
import time
import ka_identification_board as board

base=board.base
prior=board.gain.prior
TMP=board.TMP
ROOT_RESTORE=TMP/'ka-ident-restore-1792652687398602900.json'
ORDER=(0,0,0,0,0)
# Predeclared analysis-only separation. Never select windows by fitted residual,
# t_stable, or which deletion makes the slope positive. No control timing change.
STARTUP_EXCLUSION_US=600000


def analyze(capture):
    full=board.identification.report(capture)
    windows=capture['windows'];origin=windows[0]['start_us'] if windows else 0
    late=[f for f in windows if ((f['start_us']-origin)&0xffffffff)>=STARTUP_EXCLUSION_US]
    return dict(full=full,startup_exclusion_us=STARTUP_EXCLUSION_US,
        post_startup=[board.identification.fit_direction(late,d) for d in (1,-1)],
        qualification='Fixed exclusion >=600ms from observation start, not stable confirmation or residual-based deletion; one unmodified ramp per run, not a new multi-acceleration trajectory.')


def describe(values):
    values=[v for v in values if isinstance(v,(int,float)) and not isinstance(v,bool)]
    return dict(n=len(values),mean=statistics.mean(values) if values else None,
        sd=statistics.stdev(values) if len(values)>1 else None,
        min=min(values) if values else None,max=max(values) if values else None)


def summarize(runs):
    if any(r['metrics'].get('ka_compile_time')!=0 for r in runs):raise ValueError('Only Ka=0 acquisitions allowed')
    fits={}
    for label in ('full','post_startup'):
        values=[];trusted=[]
        for r in runs:
            ds=r['analysis']['full']['directions'] if label=='full' else r['analysis']['post_startup']
            d=next(x for x in ds if x['direction']==1)
            values.append(d.get('ka_identified'))
            if d['trusted']:trusted.append(d.get('ka_identified'))
        fits[label]=dict(all_finite_slopes=describe(values),trusted_only=describe(trusted),
            warning='Descriptive mean only; mixed-sign or unstable slopes are not a calibrated Ka')
    return dict(completed=len(runs)==5,runs=len(runs),gain_percent=0,
        accel_mae_rpm=describe([r['metrics'].get('accel_mae_rpm_full_precision') for r in runs]),
        fits=fits,automatic_parameter_write=False,
        qualification='Five separate run fits; no historical pooling, no averaging untrusted slopes into an approved parameter. Fitting quality failure alone does not restart or stop safe acquisition; protection/closure/evidence failure stops.')


def execute(plan_path,parent):
    if not parent.get('operator_present_whole_batch'):raise ValueError('Fresh five-run supervised powered confirmation required')
    plan=json.loads(plan_path.read_text())
    if plan.get('batch_order')!=list(ORDER) or plan.get('batch_runs')!=5 or plan.get('startup_exclusion_us')!=STARTUP_EXCLUSION_US:
        raise ValueError('Exact predeclared five-run plan required')
    base.staged(plan_path,board.image())
    previous=None
    for index in range(1,6):
        name='ka-repeat-run-'+str(time.time_ns());row=prior.new_run(name,parent,False,index)
        row.update(gain_percent=0,automatic_parameter_write=False)
        parent['attempts'].append(row['receipt_path']);parent['last_run']=row['receipt_path']
        prior.checkpoint(parent,'run_'+str(index)+'_intent');prior.checkpoint(row,'prepared')
        print('KA ACQUISITION %d/5'%index,flush=True)
        try:
            if previous is None:
                try:base.execute(row,name,plan_path,board.image())
                except RuntimeError as error:
                    if str(error)!=board.gain.EXPECTED_TERMINAL:raise
                    row['natural_terminal_note']=str(error)
            else:prior.next_run(row,name,previous)
            row['metrics']=board.classify(row)
            prior.checkpoint(row,'accepted_before_ka_fit')
            row['ka_capture']=board.identification.decode(Path(row['receipt_path']),board.ELF)
            row['analysis']=analyze(row['ka_capture'])
            row.update(acquisition_complete=True,tightening_success=False,pass_=True)
            prior.checkpoint(row,'safe_acquisition_complete')
            parent['runs'].append(dict(receipt_path=row['receipt_path'],metrics=row['metrics'],analysis=row['analysis']))
            parent['summary']=summarize(parent['runs']);prior.checkpoint(parent,'run_'+str(index)+'_saved')
            print('ACQUIRED %d/5 %s'%(index,json.dumps(row['metrics'])),flush=True)
            previous=row
        except BaseException as error:
            row['failure']=str(error)
            if row.get('hardware_attempted') and not row.get('final_cpu_halted'):
                try:base.hw.emergency_off(row,TMP/(name+'-failed.bin'))
                except Exception as off:row['cleanup_error']=str(off)
            prior.checkpoint(row,'batch_stopped_no_retry');raise
    parent.update(pass_=True,final_outputs_off=previous['final_outputs_off'],final_cpu_halted=previous['final_cpu_halted'])


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);m=p.add_mutually_exclusive_group()
    m.add_argument('--prepare-off',action='store_true');m.add_argument('--execute-five',type=Path)
    m.add_argument('--restore-b-drive-off',type=Path);p.add_argument('--baseline-restore',type=Path)
    p.add_argument('--drive-off-unlocked-no-load-fixed',action='store_true')
    p.add_argument('--operator-present-whole-batch-drive-on-no-alarm-05a',action='store_true');a=p.parse_args(argv)
    if (a.prepare_off or a.restore_b_drive_off) and not a.drive_off_unlocked_no_load_fixed:p.error('Fresh OFF confirmation required')
    if a.execute_five and not a.operator_present_whole_batch_drive_on_no_alarm_05a:p.error('Fresh whole-five-run supervised powered confirmation required')
    source=a.execute_five or a.restore_b_drive_off
    selected=a.baseline_restore or (Path(json.loads(source.read_text())['baseline_restore_receipt']) if source else ROOT_RESTORE)
    data=board.setup(selected)
    if not (a.prepare_off or source):print('OFFLINE PASS: exactly five same-image zero-Ka acquisitions; no devices');return 0
    mode='stage' if a.prepare_off else 'restore' if a.restore_b_drive_off else 'batch'
    name='ka-repeat-'+mode+'-'+str(time.time_ns())
    row=dict(mode=mode,pass_=False,receipt_path=str(TMP/(name+'.json')),steps=[],commands=[],uart=[],samples=[],postflight={},
        image_sha256=board.SHA,elf_sha256=board.ELF_SHA,baseline_restore_receipt=str(base.BASE_RESTORE_RECEIPT),
        friction_enabled=True,bemf_enabled=False,gain_percent=0,automatic_retry=False,automatic_parameter_write=False,
        runs=[],attempts=[],physical_power_off=a.drive_off_unlocked_no_load_fixed,
        operator_present_whole_batch=a.operator_present_whole_batch_drive_on_no_alarm_05a)
    prior.checkpoint(row,'prepared')
    try:
        if a.prepare_off:
            base.stage(row,name,data)
            row.update(batch_order=list(ORDER),batch_runs=5,startup_exclusion_us=STARTUP_EXCLUSION_US)
        elif a.restore_b_drive_off:base.restore(row,name,source,data)
        else:execute(source,row)
    except BaseException as error:
        row['failure']=str(error)
        if row.get('hardware_attempted') and not row.get('final_cpu_halted'):
            try:base.hw.emergency_off(row,TMP/(name+'-failed.bin'))
            except Exception as off:row['cleanup_error']=str(off)
    if mode=='batch':row['summary']=summarize(row['runs'])
    prior.checkpoint(row,'complete' if row['pass_'] else 'stopped')
    print(('PASS: ' if row['pass_'] else 'STOPPED: ')+row['receipt_path'],flush=True)
    if row.get('failure'):print(row['failure'],flush=True)
    return 0 if row['pass_'] else 1


if __name__=='__main__':raise SystemExit(main())
