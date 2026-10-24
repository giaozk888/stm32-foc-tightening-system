"""One manually selected, UNQUALIFIED Ka=2.79e-5 trial. Files only by default."""
import argparse
import hashlib
import json
from pathlib import Path
import time
import ka_full_board as previous

base=previous.base;gain=previous.gain;TMP=previous.TMP
KA=.0000279
ROOT_RESTORE=TMP/'ka-full-restore-1792658376155300100.json'
REFERENCE=TMP/'ka-full-run-1792658234874784900.json'
IMAGE=base.old.ROOT/'foc2_app_a/build/Ka279ManualTrial/foc2.bin'
ELF=IMAGE.with_suffix('.elf')
SHA='7891e9ce9b2aec45b74019b5a63a908ff236bfbafb0c24caf693244d1a984c27'
ELF_SHA='a978c8b4a893cd91c6837923931665a158f3f91d439e087fea43c6e701cdf97a'
SIZE=213004


def image():
    data=IMAGE.read_bytes()
    cmd=next(x['command'] for x in json.loads((IMAGE.parent/'compile_commands.json').read_text())
             if x['file'].endswith('/Core/Src/main.c'))
    required=('FOC_ACCEL_FF_AUDIT=1','PW_TARGET_UNIT_TESTS_DISABLED=1','PW_LOG_STORE_CAPACITY=48',
        'FOC_PROTECTED_CLOSED_LOOP=1','FOC_CURRENT_PI_IDENTIFIED_ENABLE=1','FOC_ONE_CYCLE_PWM_PIPELINE=1',
        'FOC_PWM_PIPELINE_CLOSED_LOOP=1','FOC_INTENT_FSM_CANDIDATE=1','FOC_FRICTION_ENABLED_DEFAULT=1',
        'AS5047P_DMA_FOC_FIRST=1','FOC_SPEED_PI_ANTI_WINDUP=1','FOC_ACCEL_FF_ENABLED_DEFAULT=1',
        'FOC_BEMF_ENABLED_DEFAULT=0','SPEED_FRICTION_I_A=0.105f','SPEED_ACCEL_FF_KA_A_PER_RPM_S=0.0000279f')
    if (len(data)!=SIZE or hashlib.sha256(data).hexdigest()!=SHA or
        hashlib.sha256(ELF.read_bytes()).hexdigest()!=ELF_SHA or base.hw.image_info(data)[0]!='A' or
        any('-D'+x+' ' not in cmd for x in required) or
        any('-D'+x in cmd for x in ('FOC_KA_FULL_DIAG','FOC_KA_SYNC_DIAG','FOC_KA_IDENT_DIAG',
            'FOC_STARTUP_TIMESTAMPS_DIAG','FOC_FAST_REJECT_COMPUTE_ONLY','FOC_DQ_DECOUPLING_CANDIDATE')) or
        base.symbols(ELF).get('speed_accel_audit',(0,0))[1]!=1112):
        raise ValueError('Exact reviewed manual-Ka image/ELF/flags required')
    for marker in (b'TRIP_MA=4000',b'METHOD=TWO_SAMPLE',b'TRAVEL=20000deg RAM only',
                   b'RUNDOWN240: RAM=240rpm TRIP=300rpm SAVE=OFF'):
        if marker not in data:raise ValueError('Safety/profile marker missing')
    base.support.support.require_baud(cmd)
    return data


def ff_status(line):
    v=base.hw.fields(line)
    expected=dict(ON='1',KA_NA_PER_RPM_S='27900',ACCEL_MAX_RPM_S='200',FF_PEAK_UA='5580',TOKENIZED='1')
    if any(v.get(k)!=x for k,x in expected.items()):raise RuntimeError('Exact manual Ka=27900nA/(rpm/s) readback required')
    return v


def friction_status(line,enabled):
    v=base.hw.fields(line)
    expected=dict(ON=str(int(enabled)),I_UA='105000',DB_MRPM='2000',FF_ON='1',KA_NA_PER_RPM_S='27900',TOKENIZED='1')
    if any(v.get(k)!=x for k,x in expected.items()):raise RuntimeError('Fixed friction/manual Ka readback required')
    return v


def motion(board,row):
    if row.get('manual_ka')!=KA or row.get('bemf_enabled') is not False or not row.get('friction_enabled'):
        raise ValueError('Only this manually selected Ka, BEMF OFF, fixed friction authorized')
    gain.ORIGINAL_MOTION(board,row) # Original safety/recipe/one START owner; NO GAIN command.


def decode(row):
    gain.ORIGINAL_DECODE(row)
    gain.prior.checkpoint(row,'captured_before_manual_ka_audit')
    row['accel_audit']=gain.audit.decode(Path(row['receipt_path']),ELF)


def setup(path):
    # Prove real B987 and prior full-capture A with its OLD identity first.
    previous.setup(ROOT_RESTORE);base.baseline()
    for obj in (base,gain.fitted,gain):
        obj.IMAGE,obj.ELF,obj.SHA,obj.ELF_SHA=IMAGE,ELF,SHA,ELF_SHA
        obj.image=image
    gain.fitted.SIZE=SIZE;gain.SIZE=SIZE
    base.motion=motion;gain.fitted.motion=motion;base.decode_cm=decode;gain.fitted.decode=decode
    base.ff_status=ff_status;base.friction_status=friction_status
    if path.resolve()!=ROOT_RESTORE.resolve():base.configure_baseline(path)
    return image()


def classify(row):
    metrics=gain.prior.metrics(row)
    a=row['accel_audit'];m=a['meta']
    if (a['checks']['problems'] or abs(a['ka_a_per_rpm_s']-KA)>1e-10 or
        m['samples']!=8000 or m['trajectory_updates']!=8000 or m['trace_count']!=16 or
        m['enabled_samples']!=8000 or any(m[k] for k in ('sign_errors','zero_ff_errors','formula_errors','sync_errors')) or
        m['max_abs_ff']>KA*200+1e-6 or m['max_ff_limit_ratio']>.011162):
        raise RuntimeError('Manual Ka formula/direction/trajectory/limit evidence invalid; no retry')
    metrics.update(mode='KA279_ON',manual_ka=KA,qualified_identification=False,
        max_abs_ff_a=m['max_abs_ff'],max_ff_limit_ratio=m['max_ff_limit_ratio'],
        aw_limited_samples=m['aw_limited_samples'],unexpected_aw_samples=m['unexpected_aw_samples'])
    return metrics


def comparison(row):
    ref=json.loads(REFERENCE.read_text())
    if not ref.get('pass_') or ref.get('metrics',{}).get('ka_compile_time')!=0:
        raise ValueError('Exact completed Ka=0 reference required')
    names=('accel_mae_rpm','cruise_mae_rpm','overshoot_rpm','iq_ref_peak_a','integrator_peak_a')
    old=ref['metrics'];new=row['metrics']
    return dict(reference=str(REFERENCE),strict_ab=False,single_run_only=True,
        candidate_minus_reference={k:new[k]-old[k] for k in names},
        warning='Historical full-capture Ka=0 vs this audit Ka=2.79e-5: different diagnostic loads and independent starts. Descriptive only, NOT a same-image randomized/repeated A/B or proof of improvement.')


def execute(row,name,plan,data):
    try:base.execute(row,name,plan,data)
    except RuntimeError as error:
        if str(error)!=gain.EXPECTED_TERMINAL:raise
        row['natural_terminal_note']=str(error)
    row['metrics']=classify(row);row['historical_reference']=comparison(row)
    row.update(pass_=True,acquisition_complete=True,tightening_success=False)


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);m=p.add_mutually_exclusive_group()
    m.add_argument('--prepare-off',action='store_true');m.add_argument('--execute-powered',type=Path)
    m.add_argument('--restore-b-drive-off',type=Path);p.add_argument('--baseline-restore',type=Path)
    p.add_argument('--drive-off-unlocked-no-load-fixed',action='store_true')
    p.add_argument('--operator-present-drive-on-no-alarm-05a',action='store_true');a=p.parse_args(argv)
    if (a.prepare_off or a.restore_b_drive_off) and not a.drive_off_unlocked_no_load_fixed:p.error('Fresh OFF required')
    if a.execute_powered and not a.operator_present_drive_on_no_alarm_05a:p.error('Fresh supervised powered confirmation required')
    source=a.execute_powered or a.restore_b_drive_off
    selected=a.baseline_restore or (Path(json.loads(source.read_text())['baseline_restore_receipt']) if source else ROOT_RESTORE)
    data=setup(selected)
    if not(a.prepare_off or source):print('OFFLINE PASS: one manual unqualified Ka trial; no devices');return 0
    mode='stage' if a.prepare_off else 'restore' if a.restore_b_drive_off else 'run'
    name='ka279-'+mode+'-'+str(time.time_ns())
    row=dict(mode=mode,pass_=False,receipt_path=str(TMP/(name+'.json')),steps=[],commands=[],uart=[],samples=[],postflight={},
        image_sha256=SHA,elf_sha256=ELF_SHA,baseline_restore_receipt=str(base.BASE_RESTORE_RECEIPT),
        physical_power_off=a.drive_off_unlocked_no_load_fixed,powered_no_alarm=a.operator_present_drive_on_no_alarm_05a,
        start_attempts=0,automatic_retry=False,automatic_parameter_write=False,manual_ka=KA,qualified_identification=False,
        friction_enabled=True,bemf_enabled=False,speed_target_rpm=240,speed_iq_limit_A=.50,overspeed_trip_rpm=300,
        host_max_seconds=base.HOST_MAX_SECONDS)
    gain.prior.checkpoint(row,'prepared')
    try:
        if a.prepare_off:base.stage(row,name,data)
        elif a.restore_b_drive_off:base.restore(row,name,source,data)
        else:execute(row,name,source,data)
    except BaseException as error:
        row['failure']=str(error)
        if row.get('hardware_attempted') and not row.get('final_cpu_halted'):
            try:base.hw.emergency_off(row,TMP/(name+'-failed.bin'))
            except Exception as off:row['cleanup_error']=str(off)
    gain.prior.checkpoint(row,'complete' if row['pass_'] else 'stopped')
    print(('PASS: ' if row['pass_'] else 'STOPPED: ')+row['receipt_path'],flush=True)
    if row.get('failure'):print(row['failure'],flush=True)
    return 0 if row['pass_'] else 1

if __name__=='__main__':raise SystemExit(main())
