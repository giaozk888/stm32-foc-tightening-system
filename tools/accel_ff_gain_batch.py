"""Six supervised paired acceleration-FF gains. Default FILES ONLY.

One OFF staging of diagnostic A; idle-only gain selection, never powered
programming. Original FSM/START/calibration/health/shutdown owners retained.
"""
import argparse
import hashlib
import json
from pathlib import Path
import time
import bemf_repeat_batch as prior
import accel_ff_audit_report as audit

fitted=prior.fitted
base=prior.base
TMP=base.TMP
ROOT_RESTORE=TMP/'bemf-fitted-restore-1792643440402562700.json'
IMAGE=base.old.ROOT/'foc2_app_a/build/AccelFfAuditGain100/foc2.bin'
ELF=IMAGE.with_suffix('.elf')
SHA='0f34df867e0f13ba9e544a89253400936efb4616d33bd2a2027da7731363f6b1'
ELF_SHA='28758a2459e03806f20a718389007be566eBD56051dcac2fa1c54c3f2e384337'.lower()
SIZE=220620
ORDER=(0,25,0,50,0,100)
ORIGINAL_MOTION=fitted.motion
ORIGINAL_DECODE=fitted.decode
EXPECTED_TERMINAL=prior.EXPECTED_TERMINAL
current_gain=100


def image():
    data=IMAGE.read_bytes()
    cmd=next(c['command'] for c in json.loads((IMAGE.parent/'compile_commands.json').read_text())
        if c['file'].endswith('/Core/Src/main.c'))
    required=('FOC_ACCEL_FF_AUDIT=1','FOC_BEMF_ENABLED_DEFAULT=0',
        'FOC_CURRENT_PI_IDENTIFIED_ENABLE=1','FOC_ONE_CYCLE_PWM_PIPELINE=1',
        'FOC_PWM_PIPELINE_CLOSED_LOOP=1','FOC_INTENT_FSM_CANDIDATE=1',
        'FOC_FRICTION_ENABLED_DEFAULT=1','AS5047P_DMA_FOC_FIRST=1',
        'FOC_SPEED_PI_ANTI_WINDUP=1','FOC_ACCEL_FF_ENABLED_DEFAULT=1',
        'SPEED_FRICTION_I_A=0.105f','SPEED_ACCEL_FF_KA_A_PER_RPM_S=0.0001875f')
    if (len(data)!=SIZE or hashlib.sha256(data).hexdigest()!=SHA or
        hashlib.sha256(ELF.read_bytes()).hexdigest()!=ELF_SHA or
        base.hw.image_info(data)[0]!='A' or any('-D'+x+' ' not in cmd for x in required) or
        any('-D'+x in cmd for x in ('FOC_PSI_IDENT','FOC_DQ_DECOUPLING_CANDIDATE',
            'FOC_CURRENT_STEP_AB_DIAG','FOC_FAST_REJECT_COMPUTE_ONLY')) or
        base.symbols(ELF).get('speed_accel_audit',(0,0))[1]!=1112):
        raise ValueError('Exact tested acceleration audit BIN/ELF/flags/ABI required')
    for marker in (b'MOTOR TEST FF GAIN ',b'TRIP_MA=4000',b'METHOD=TWO_SAMPLE',
        b'RUNDOWN240: RAM=240rpm TRIP=300rpm SAVE=OFF',b'TRAVEL=20000deg RAM only'):
        if marker not in data:raise ValueError('Diagnostic/protection marker missing')
    base.support.support.require_baud(cmd)
    return data


def ff_status(line):
    values=base.hw.fields(line)
    ka=round(.0001875*current_gain/100*1e9)
    expected=dict(ON='1',KA_NA_PER_RPM_S=str(ka),ACCEL_MAX_RPM_S='200',
        FF_PEAK_UA=str(round(.0375*current_gain/100*1e6)),TOKENIZED='1')
    if any(values.get(k)!=v for k,v in expected.items()):raise RuntimeError('Exact selected FF gain required; no START')
    return values


def friction_status(line,enabled):
    values=base.hw.fields(line)
    expected=dict(ON=str(int(enabled)),I_UA='105000',DB_MRPM='2000',FF_ON='1',
        KA_NA_PER_RPM_S=str(round(.0001875*current_gain/100*1e9)),TOKENIZED='1')
    if any(values.get(k)!=v for k,v in expected.items()):raise RuntimeError('Fixed friction/selected FF readback required')
    return values


def motion(board,row):
    global current_gain
    current_gain=row['gain_percent']
    if current_gain not in ORDER:raise ValueError('Unsupported gain; no START')
    # Firmware itself independently rejects non-idle / enabled power outputs.
    row['gain_switch']=ff_status(board.command('MOTOR TEST FF GAIN '+str(current_gain)))
    ORIGINAL_MOTION(board,row) # BEMF OFF and original protected START owner.


def decode(row):
    ORIGINAL_DECODE(row)
    # Full capture is already written; exact identity is checked by decoder.
    # Receipt checkpoint must precede the file-only decoder.
    prior.checkpoint(row,'captured_before_audit_decode')
    row['accel_audit']=audit.decode(Path(row['receipt_path']),ELF)


def setup(path):
    # Prove old confirmed B951 under its OLD exact A before installing new A verifier.
    fitted.configure(ROOT_RESTORE)
    base.baseline()
    fitted.IMAGE,fitted.ELF,fitted.SHA,fitted.ELF_SHA,fitted.SIZE=IMAGE,ELF,SHA,ELF_SHA,SIZE
    fitted.image=image;fitted.motion=motion;fitted.decode=decode
    base.IMAGE,base.ELF,base.SHA,base.ELF_SHA=IMAGE,ELF,SHA,ELF_SHA
    base.image=image;base.motion=motion;base.decode_cm=decode
    base.ff_status=ff_status;base.friction_status=friction_status
    base.staged=fitted.ORIGINAL_STAGED
    base.TokenRecordedBoard=prior.BatchBoard
    if path.resolve()!=ROOT_RESTORE.resolve():base.configure_baseline(path)
    image()


def metrics(row):
    result=prior.metrics(row)
    a=row['accel_audit'];m=a['meta'];ka=.0001875*row['gain_percent']/100
    if (row['bemf_enabled'] or a['bemf_runtime']!='0' or a['checks']['problems'] or
        abs(a['ka_a_per_rpm_s']-ka)>1e-10 or m['samples']!=8000 or m['trace_count']!=16 or
        m['trajectory_updates']!=8000 or m['enabled_samples']!=8000 or
        any(m[x] for x in ('sign_errors','zero_ff_errors','formula_errors','sync_errors')) or
        m['max_abs_ff']>abs(ka)*200+1e-6):
        raise RuntimeError('Acceleration gain/formula/trajectory/coverage evidence invalid; stop')
    result.update(gain_percent=row['gain_percent'],mode=str(row['gain_percent']),
        max_abs_ff_a=m['max_abs_ff'],aw_limited_samples=m['aw_limited_samples'],
        unexpected_aw_samples=m['unexpected_aw_samples'],pi_ff_opposed_samples=m['pi_ff_opposed'])
    return result


def summarize(runs):
    pairs=[]
    for i in range(0,len(runs)-1,2):
        off,on=(r['metrics'] for r in runs[i:i+2])
        pairs.append(dict(gain_percent=on['gain_percent'],baseline=off,candidate=on,
            candidate_minus_baseline={k:on[k]-v for k,v in off.items()
                if k not in ('gain_percent',) and isinstance(v,(int,float)) and isinstance(on.get(k),(int,float))}))
    return dict(completed=len(runs)==6,paired=pairs,
        qualification='One observation per nonzero gain, not three repeats per gain; no automatic gain selection')


def execute(plan_path,parent,order=ORDER,summary_fn=summarize,metrics_fn=None):
    if not parent.get('operator_present_whole_batch'):raise ValueError('Fresh supervised powered confirmation required')
    if order not in (ORDER,(25,25,25,25,25),(25,25,25,25,25,25)):raise ValueError('Only explicitly supported fixed batches allowed')
    classify_run=metrics if metrics_fn is None else metrics_fn
    plan=json.loads(plan_path.read_text())
    if plan.get('batch_order')!=list(order) or plan.get('batch_runs')!=len(order):raise ValueError('Exact fixed batch plan required')
    base.staged(plan_path,image())
    previous=None
    for index,gain in enumerate(order,1):
        name='accel-gain-run-'+str(time.time_ns())
        row=prior.new_run(name,parent,False,index);row['gain_percent']=gain
        parent['attempts'].append(row['receipt_path']);parent['last_run']=row['receipt_path']
        prior.checkpoint(parent,'run_'+str(index)+'_intent');prior.checkpoint(row,'prepared')
        print('ACCEL GAIN RUN %d/%d %d%%'%(index,len(order),gain),flush=True)
        try:
            if previous is None:
                try:base.execute(row,name,plan_path,image())
                except RuntimeError as error:
                    if str(error)!=EXPECTED_TERMINAL:raise
                    row['natural_terminal_note']=str(error)
            else:prior.next_run(row,name,previous)
            row['metrics']=classify_run(row);row['acquisition_complete']=True;row['tightening_success']=False
            prior.checkpoint(row,'natural_no_load_timeout_acquired')
            parent['runs'].append(dict(receipt_path=row['receipt_path'],metrics=row['metrics']))
            parent['summary']=summary_fn(parent['runs']);prior.checkpoint(parent,'run_'+str(index)+'_saved')
            print('ACQUIRED %d/%d %s'%(index,len(order),json.dumps(row['metrics'])),flush=True)
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
    m.add_argument('--prepare-off',action='store_true');m.add_argument('--execute-six',type=Path)
    m.add_argument('--restore-b-drive-off',type=Path)
    p.add_argument('--baseline-restore',type=Path)
    p.add_argument('--drive-off-unlocked-no-load-fixed',action='store_true')
    p.add_argument('--operator-present-whole-batch-drive-on-no-alarm-05a',action='store_true');a=p.parse_args(argv)
    if (a.prepare_off or a.restore_b_drive_off) and not a.drive_off_unlocked_no_load_fixed:p.error('Fresh drive OFF required')
    if a.execute_six and not a.operator_present_whole_batch_drive_on_no_alarm_05a:p.error('Fresh supervised powered confirmation required')
    source=a.execute_six or a.restore_b_drive_off
    selected=a.baseline_restore or (Path(json.loads(source.read_text())['baseline_restore_receipt']) if source else ROOT_RESTORE)
    setup(selected)
    if not (a.prepare_off or source):print('OFFLINE PASS: exact gain batch 0/25/0/50/0/100; no devices');return 0
    mode='stage' if a.prepare_off else 'restore' if a.restore_b_drive_off else 'batch'
    name='accel-gain-'+mode+'-'+str(time.time_ns())
    row=dict(mode=mode,pass_=False,receipt_path=str(TMP/(name+'.json')),steps=[],commands=[],uart=[],samples=[],
        postflight={},runs=[],attempts=[],image_sha256=SHA,elf_sha256=ELF_SHA,
        baseline_restore_receipt=str(base.BASE_RESTORE_RECEIPT),friction_enabled=True,bemf_enabled=False,
        physical_power_off=a.drive_off_unlocked_no_load_fixed,automatic_retry=False,
        operator_present_whole_batch=a.operator_present_whole_batch_drive_on_no_alarm_05a)
    prior.checkpoint(row,'prepared')
    try:
        if a.prepare_off:
            base.stage(row,name,image());row['batch_order']=list(ORDER);row['batch_runs']=6
        elif a.restore_b_drive_off:base.restore(row,name,source,image())
        else:execute(a.execute_six,row)
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
