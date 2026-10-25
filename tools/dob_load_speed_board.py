"""One supervised RUNDOWN load-speed240/120 candidate trial, files-only default.
Original one START, protections, physical OFF stage and separate OFF B restore.
"""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import time
import dob_warmup_ab_board as previous
import dob_low_audit_board as stopped_audit
import dob_load_speed_decode as load_speed_decode
base=previous.base;normal=previous.normal;continuous=previous.continuous;TMP=previous.TMP
ROOT_RESTORE=TMP/'dob-low-audit-restore-1792837575414166600.json'
IMAGE=base.old.ROOT/'foc2_app_a/build/DobLoadSpeedCandidate/foc2.bin'
ELF=IMAGE.with_suffix('.elf')
SHA='06b0c15943965e06ed409ad4190adf9fda78ae20c4f8592c66cfb518d0e23160'
ELF_SHA='6f075dfd4b6017a4f3b2216d6deb3eb6f121152e5f7a41ff9b6bab35859164d8'
SIZE=228352
WINDOW=dict(WINDOW_MS='75',MIN_GOOD='45',MIN_SPAN_US='45000',TREND_TAU_US='100000',
    TREND_DWELL_US='80000',LEVEL_DWELL_US='30000')
WARM=dict(TAU='3',BW_MHZ='2000',DEFAULT_TAU='3',RAM_ONLY='1')

def image():
    data=IMAGE.read_bytes()
    if len(data)!=SIZE or hashlib.sha256(data).hexdigest()!=SHA or hashlib.sha256(ELF.read_bytes()).hexdigest()!=ELF_SHA:
        raise ValueError('Exact reviewed window75 warmup3 BIN/ELF required')
    cmd=next(c['command'] for c in json.loads((IMAGE.parent/'compile_commands.json').read_text()) if c['file'].endswith('/Core/Src/main.c'))
    for flag in ('FOC_DOB_LOAD_SPEED=1','FOC_DOB_TREND_WINDOW75=1','FOC_DOB_WARMUP_AB=1','DOB_WARMUP_DEFAULT_TAU=3U',
        'FOC_DOB_SATURATION_CONTINUE=1','FOC_DOB_TREND_CONTINUOUS=1','FOC_NORMAL_RUN_TRIP500=1',
        'FOC_DOB_NORMAL_CONTROL=1','FOC_DOB_CONTACT20_OBSERVE10=1','FOC_DOB_ID_PRE_LPF_QUALITY=1',
        'FOC_ONE_CYCLE_PWM_PIPELINE=1','DOB_ADMIT_JUMP_A=.200f','DOB_FB_GAIN=0.25f'):
        if '-D'+flag+' ' not in cmd:raise ValueError('Required profile '+flag)
    for flag in ('FOC_DOB_SHORT_LOW_RECOVERY','FOC_DOB_LOW_AUDIT','FOC_DOB_RECOVERY_TIMING','FOC_DOB_REAL_TRACE','FOC_DOB_ID_TRACE','FOC_DOB_GAIN_AB_DIAG','FOC_MECHANICAL_HIGH_SPEED_DIAG'):
        if '-D'+flag+'=1 ' in cmd:raise ValueError('Conflicting diagnostic '+flag)
    for name,n in dict(dob_load_speed=60,dob_warmup_tau=4,dob_saturation_audit=32,dob_trend_continuous=100,
        dob_trend_continuous_arena=4,mechanical_capture=4712,dob_feedback=80,mechanical_dob_monitor=856,
        dob_current_admission=204).items():
        if base.symbols(ELF).get(name,(0,0))[1]!=n:raise ValueError('Unchanged ABI '+name)
    if base.hw.image_info(data)[0]!='A' or b'RUNDOWN240: RAM=240rpm TRIP=500rpm SAVE=OFF' not in data:
        raise ValueError('Normal A identity missing')
    return data

def configure(path):
    stopped_audit.configure(ROOT_RESTORE) # Validate exact latest stopped B1250 and audit A before candidate selection.
    for obj in (base,continuous):
        for key in ('IMAGE','ELF','SHA','ELF_SHA','SIZE'):setattr(obj,key,globals()[key])
    base.image=image;base.motion=motion;base.decode_cm=decode;base.staged=normal.ORIGINAL_STAGED
    if Path(path).resolve()!=ROOT_RESTORE.resolve():base.configure_baseline(Path(path))
    return image()

def motion(board,row):
    normal.check_values(board.command('MOTOR TEST MECH DOB FB CFG'),dict(normal.FB_CONFIG,ON='0'),'Boot feedback OFF')
    row['window_config']=normal.check_values(board.command('MOTOR TEST MECH DOB WINDOW CFG'),WINDOW,'Selected tested window75')
    row['warmup_config']=normal.check_values(board.command('MOTOR TEST MECH DOB WARM CFG'),WARM,'Selected default3tau')
    try:previous.prior.motion(board,row) # Same SAT/limits/FB ON/preflight/START route.
    finally:
        for cmd in ('MOTOR TEST MECH DOB WINDOW CFG','MOTOR TEST MECH DOB WARM CFG'):
            row['postflight'][cmd]=board.command(cmd)

def decode(row):
    continuous.decode(row)
    ram=Path(row['ram_capture']).read_bytes();syms=base.symbols(ELF)
    a,n=syms['dob_saturation_audit'];audit=dict(zip(previous.prior.AUDIT_KEYS,struct.unpack_from('<8I',ram,a-0x20000000)))
    a,n=syms['dob_warmup_tau'];tau=struct.unpack_from('<I',ram,a-0x20000000)[0]
    if tau!=3 or audit['samples']!=row['trend_capture']['header']['observations']:
        raise ValueError('Captured tau / sample closure')
    if any(v>audit['samples'] for k,v in audit.items() if k!='limited_valid'):raise ValueError('Audit counters')
    row.update(actual_tau_ram=tau,saturation_audit=audit)
    telemetry=load_speed_decode.decode(ram,syms)
    trace_path=Path(row['receipt_path']).with_suffix('.loadspeed.json')
    trace_path.write_text(json.dumps(telemetry,indent=2,allow_nan=False)+'\n')
    row['load_speed_capture']=dict(telemetry,path=str(trace_path),sha256=hashlib.sha256(trace_path.read_bytes()).hexdigest())
    if row.get('start_attempts')==1:
        normal.check_values(row['postflight']['MOTOR TEST MECH DOB WINDOW CFG'],WINDOW,'Post-run window configuration')
        normal.check_values(row['postflight']['MOTOR TEST MECH DOB WARM CFG'],WARM,'Post-run warmup configuration')

def record(*args):
    row=previous.record(*args);row.pop('schedule',None)
    row.update(image_sha256=SHA,elf_sha256=ELF_SHA,window_ms=75,window_min_good=45,
        window_min_span_us=45000,warmup_tau_requested=3,all_other_limits_preserved=True,load_speed_candidate=True,slow_target_rpm=120,
        high_dwell_us=30000,release_dwell_us=200000,invalid_fallback_us=200000)
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
        p.error('Fresh powered/no-alarm/operator/dynamic-brake confirmation required')
    source=a.execute_powered or a.restore_b_drive_off
    baseline=Path(json.loads(source.read_text())['baseline_restore_receipt']) if source else ROOT_RESTORE
    data=configure(baseline)
    if not a.stage_off and not source:print('OFFLINE PASS: pinned load-speed240/120 / window75 / warmup3 A; no devices');return 0
    mode='stage' if a.stage_off else 'restore' if a.restore_b_drive_off else 'run'
    name='dob-load-speed-'+mode+'-'+str(time.time_ns())
    row=record(mode,name,baseline,a.drive_off_brake_released_fixed_guarded,a.operator_present_drive_on_no_alarm_05a)
    base.old.prior.checkpoint(row,'prepared')
    try:
        if a.stage_off:base.stage(row,name,data)
        elif a.restore_b_drive_off:base.restore(row,name,source,data)
        else:
            plan=json.loads(source.read_text())
            if plan.get('window_ms')!=75 or plan.get('warmup_tau_requested')!=3 or plan.get('load_speed_candidate') is not True:raise ValueError('Exact staged window75/3tau plan required')
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
