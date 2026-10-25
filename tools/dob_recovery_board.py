"""One supervised recovery-partition trial. Separate OFF-stage/ON-run/OFF-B.
No motor retry, parameter retuning, threshold change or automatic re-arm.
"""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import time
import dob_window75_board as previous
import dob_recovery_decode as recovery
base=previous.base;normal=previous.normal;continuous=previous.continuous;TMP=previous.TMP
ROOT_RESTORE=TMP/'dob-window75-restore-1792828854599051500.json'
IMAGE=base.old.ROOT/'foc2_app_a/build/DobRecoveryBreakdownCandidate/foc2.bin'
ELF=IMAGE.with_suffix('.elf')
SHA='93b4b7eacf756d59c117b5a279fcf27f2eebb3e7aca223da633ac18f2465c321'
ELF_SHA='31cf1dd7f4fcec0b1e349958d51a37a2313e6bca9146b9b57448da9435c3d27f'
SIZE=228712
CFG=dict(ABI='1',RECORDS='3',BYTES='48',PENDING='1',RESOLUTION_US='1000',READ='HALTED_RAM',DEFAULT_TAU='3',WINDOW_MS='75')
OLD_CONFIGURE=previous.configure;OLD_MOTION=previous.motion;OLD_DECODE=previous.decode;OLD_RECORD=previous.record

def image():
    data=IMAGE.read_bytes()
    if len(data)!=SIZE or hashlib.sha256(data).hexdigest()!=SHA or hashlib.sha256(ELF.read_bytes()).hexdigest()!=ELF_SHA:
        raise ValueError('Exact reviewed recovery BIN/ELF required')
    cmd=next(c['command'] for c in json.loads((IMAGE.parent/'compile_commands.json').read_text()) if c['file'].endswith('/Core/Src/main.c'))
    for flag in ('FOC_DOB_RECOVERY_TIMING=1','FOC_DOB_TREND_WINDOW75=1','FOC_DOB_WARMUP_AB=1','DOB_WARMUP_DEFAULT_TAU=3U',
        'FOC_DOB_SATURATION_CONTINUE=1','FOC_DOB_TREND_CONTINUOUS=1','FOC_NORMAL_RUN_TRIP500=1',
        'FOC_DOB_NORMAL_CONTROL=1','FOC_DOB_CONTACT20_OBSERVE10=1','FOC_DOB_ID_PRE_LPF_QUALITY=1',
        'FOC_ONE_CYCLE_PWM_PIPELINE=1','DOB_ADMIT_JUMP_A=.200f','DOB_FB_GAIN=0.25f'):
        if '-D'+flag+' ' not in cmd:raise ValueError('Required profile '+flag)
    for flag in ('FOC_DOB_REAL_TRACE','FOC_DOB_ID_TRACE','FOC_DOB_GAIN_AB_DIAG','FOC_MECHANICAL_HIGH_SPEED_DIAG'):
        if '-D'+flag+'=1 ' in cmd:raise ValueError('Conflicting profile '+flag)
    for name,n in dict(dob_recovery_timing=68,dob_warmup_tau=4,dob_saturation_audit=32,dob_trend_continuous=100,
        dob_trend_continuous_arena=4,mechanical_capture=4712,dob_feedback=80,mechanical_dob_monitor=856,dob_current_admission=204).items():
        if base.symbols(ELF).get(name,(0,0))[1]!=n:raise ValueError('ABI '+name)
    if base.hw.image_info(data)[0]!='A' or b'RUNDOWN240: RAM=240rpm TRIP=500rpm SAVE=OFF' not in data:
        raise ValueError('Normal A/500rpm identity absent')
    return data

def configure(path):
    OLD_CONFIGURE(ROOT_RESTORE) # Original preserved B1234 and exact previous window75 A first.
    for obj in (previous,continuous,base):
        for key in ('IMAGE','ELF','SHA','ELF_SHA','SIZE'):setattr(obj,key,globals()[key])
    base.image=image;base.motion=motion;base.decode_cm=decode;base.staged=normal.ORIGINAL_STAGED
    if Path(path).resolve()!=ROOT_RESTORE.resolve():base.configure_baseline(Path(path))
    return image()

def motion(board,row):
    row['recovery_config']=normal.check_values(board.command('MOTOR TEST MECH DOB RECOVERY CFG'),CFG,'Passive recovery timing')
    try:OLD_MOTION(board,row)
    finally:row['postflight']['MOTOR TEST MECH DOB RECOVERY CFG']=board.command('MOTOR TEST MECH DOB RECOVERY CFG')

def decode(row):
    OLD_DECODE(row)
    if row.get('start_attempts')!=1:
        row['recovery_capture']=dict(available=False,reason='START not issued; preflight must not initialize run timing')
        return
    trace=recovery.load(ram=Path(row['ram_capture']),elf=ELF)
    n=row['trend_capture']['header']['observations'];h=trace['header']
    if not n<=h['calls']<=n+1:raise ValueError('Recovery task/RUN count closure')
    if h['last_classifier_resets']!=row['trend_capture']['coverage']['classifier']['resets']:
        raise ValueError('Classifier reset/timing closure')
    normal.check_values(row['postflight']['MOTOR TEST MECH DOB RECOVERY CFG'],CFG,'Saved recovery configuration')
    path=Path(row['receipt_path']).with_suffix('.recovery.json');path.write_text(json.dumps(trace,indent=2)+'\n')
    if trace['records']:
        import csv
        with path.with_suffix('.csv').open('w',newline='',encoding='utf-8') as f:
            writer=csv.DictWriter(f,fieldnames=trace['records'][0]);writer.writeheader();writer.writerows(trace['records'])
    row['recovery_capture']=dict(trace,available=True,json=str(path),json_sha256=hashlib.sha256(path.read_bytes()).hexdigest())

def record(*args):
    row=OLD_RECORD(*args)
    row.update(image_sha256=SHA,elf_sha256=ELF_SHA,recovery_stage_timing=True)
    return row

def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);g=p.add_mutually_exclusive_group()
    g.add_argument('--stage-off',action='store_true');g.add_argument('--execute-powered',type=Path)
    g.add_argument('--restore-b-drive-off',type=Path)
    p.add_argument('--drive-off-brake-released-fixed-guarded',action='store_true')
    p.add_argument('--operator-present-drive-on-no-alarm-05a',action='store_true')
    p.add_argument('--dynamic-brake-immediately-releasable',action='store_true');a=p.parse_args(argv)
    if (a.stage_off or a.restore_b_drive_off) and not a.drive_off_brake_released_fixed_guarded:p.error('Physical12V OFF required')
    if a.execute_powered and not (a.operator_present_drive_on_no_alarm_05a and a.dynamic_brake_immediately_releasable):
        p.error('Fresh powered/no-alarm/operator/dynamic brake confirmation required')
    source=a.execute_powered or a.restore_b_drive_off
    baseline=Path(json.loads(source.read_text())['baseline_restore_receipt']) if source else ROOT_RESTORE
    data=configure(baseline)
    if not a.stage_off and not source:print('OFFLINE PASS: pinned recovery3tau/window75; no devices');return 0
    mode='stage' if a.stage_off else 'restore' if a.restore_b_drive_off else 'run'
    name='dob-recovery-'+mode+'-'+str(time.time_ns())
    row=record(mode,name,baseline,a.drive_off_brake_released_fixed_guarded,a.operator_present_drive_on_no_alarm_05a)
    base.old.prior.checkpoint(row,'prepared')
    try:
        if a.stage_off:base.stage(row,name,data)
        elif a.restore_b_drive_off:base.restore(row,name,source,data)
        else:
            plan=json.loads(source.read_text())
            if plan.get('recovery_stage_timing') is not True:raise ValueError('Exact recovery stage plan required')
            try:normal.ORIGINAL_EXECUTE(row,name,source,data)
            except RuntimeError as error:
                expected='FSM terminal '+row.get('terminal_status',{}).get('OUTCOME','UNKNOWN')+'; no-load observation is not successful tightening; no retry'
                if str(error)!=expected:raise
            row['result']=normal.classify(row);cov=row['trend_capture']['coverage']
            if not cov['observer_counts_match'] or not cov['full_observed_run']:raise RuntimeError('Whole-RUN evidence incomplete')
            row['pass_']=True
    except BaseException as error:
        row['failure']=str(error)
        if row.get('hardware_attempted') and not row.get('final_cpu_halted'):
            try:base.hw.emergency_off(row,TMP/(name+'-failed.bin'))
            except Exception as off:row['cleanup_error']=str(off)
    base.old.prior.checkpoint(row,'complete' if row['pass_'] else 'stopped_no_retry')
    print(('PASS: ' if row['pass_'] else 'STOPPED: ')+row['receipt_path'],flush=True)
    if row.get('failure'):print(row['failure'],flush=True)
    return 0 if row['pass_'] else 1
if __name__=='__main__':raise SystemExit(main())
