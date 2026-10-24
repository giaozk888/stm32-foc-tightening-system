"""One supervised full acceleration Ka capture. Files only unless explicit OFF/ON mode."""
import argparse
import hashlib
import json
from pathlib import Path
import time
import ka_sync_motion_board as previous
import ka_full_report as report

base=previous.base;gain=previous.gain;TMP=previous.TMP
ROOT_RESTORE=TMP/'ka-sync-motion-restore-1792656303784481500.json'
IMAGE=base.old.ROOT/'foc2_app_a/build/KaFullAccelerationDiagnostic/foc2.bin'
ELF=IMAGE.with_suffix('.elf')
SHA='5bf45ca701767f0d4b8c98bd7188167a09b24eddb9be341a4a19f11a76c84c0b'
ELF_SHA='0120c4208ba2d0b85e3249b26e504105f901d10141fa92cced0b85ded1878a83'
SIZE=211960


def image():
    data=IMAGE.read_bytes()
    cmd=next(x['command'] for x in json.loads((IMAGE.parent/'compile_commands.json').read_text())
             if x['file'].endswith('/Core/Src/main.c'))
    required=('FOC_KA_FULL_DIAG=1','PW_TARGET_UNIT_TESTS_DISABLED=1','PW_LOG_STORE_CAPACITY=48',
        'FOC_PROTECTED_CLOSED_LOOP=1','FOC_CURRENT_PI_IDENTIFIED_ENABLE=1',
        'FOC_ONE_CYCLE_PWM_PIPELINE=1','FOC_PWM_PIPELINE_CLOSED_LOOP=1',
        'FOC_INTENT_FSM_CANDIDATE=1','FOC_FRICTION_ENABLED_DEFAULT=1','AS5047P_DMA_FOC_FIRST=1',
        'FOC_SPEED_PI_ANTI_WINDUP=1','FOC_ACCEL_FF_ENABLED_DEFAULT=1','FOC_BEMF_ENABLED_DEFAULT=0',
        'SPEED_FRICTION_I_A=0.105f','SPEED_ACCEL_FF_KA_A_PER_RPM_S=0.0000000f')
    if (len(data)!=SIZE or hashlib.sha256(data).hexdigest()!=SHA or
        hashlib.sha256(ELF.read_bytes()).hexdigest()!=ELF_SHA or base.hw.image_info(data)[0]!='A' or
        any('-D'+x+' ' not in cmd for x in required) or
        any('-D'+x in cmd for x in ('FOC_KA_SYNC_DIAG','FOC_KA_IDENT_DIAG','FOC_ACCEL_FF_AUDIT',
            'FOC_STARTUP_TIMESTAMPS_DIAG','FOC_FAST_REJECT_COMPUTE_ONLY','FOC_DQ_DECOUPLING_CANDIDATE'))):
        raise ValueError('Exact offline-tested full Ka A BIN/ELF/flags required')
    syms=base.symbols(ELF)
    if syms.get('ka_full_diagnostic',(0,0))[1]!=5872 or syms.get('ka_sync_current',(0,0))[1]!=20:
        raise ValueError('Exact full diagnostic/publication ABI required')
    for marker in (b'TRIP_MA=4000',b'METHOD=TWO_SAMPLE',b'TRAVEL=20000deg RAM only',
                   b'RUNDOWN240: RAM=240rpm TRIP=300rpm SAVE=OFF'):
        if marker not in data:raise ValueError('Safety/profile marker missing')
    base.support.support.require_baud(cmd)
    return data


def decode(row):
    gain.ORIGINAL_DECODE(row)
    gain.prior.checkpoint(row,'captured_before_full_decode')
    row['full_saved']=report.decode(Path(row['receipt_path']),ELF)


def motion(board,row):
    # Original calibrated/protected/recipe/lease/STOP owner, one START only.
    previous.sync.previous.motion(board,row)


def setup(path):
    # Validate the real B983/old sync identity FIRST, never relabel its receipt.
    previous.setup(ROOT_RESTORE);base.baseline()
    for obj in (base,gain.fitted,gain):
        obj.IMAGE,obj.ELF,obj.SHA,obj.ELF_SHA=IMAGE,ELF,SHA,ELF_SHA
        obj.image=image
    gain.fitted.SIZE=SIZE;gain.SIZE=SIZE;gain.current_gain=0
    base.motion=motion;gain.fitted.motion=motion
    base.decode_cm=decode;gain.fitted.decode=decode
    if path.resolve()!=ROOT_RESTORE.resolve():base.configure_baseline(path)
    return image()


def classify(row):
    metrics=gain.prior.metrics(row)
    c=row['full_saved']
    c['board_acceptance_verified']=True # Only after original full health classifier returned.
    if not c['complete'] or not c['reference_acceleration_covered']:
        raise RuntimeError('Complete acceleration/reference coverage missing; preserve data, no retry')
    metrics.update(ka_compile_time=0,full_bins=len(c['frames']),full_span_us=c['span_us'],
        observations=c['meta']['observations'],capture_quality_valid=c['all_observations_valid'],
        current_minus_encoder_us=c['current_minus_encoder_us'],publisher_max_us=c['publisher_max_us'])
    return metrics


def execute(row,name,plan,data):
    try:base.execute(row,name,plan,data)
    except RuntimeError as error:
        if str(error)!=gain.EXPECTED_TERMINAL:raise
        row['natural_terminal_note']=str(error)
    row['metrics']=classify(row)
    row['ka_fit']=report.report(row['full_saved'])
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
    if not(a.prepare_off or source):print('OFFLINE PASS: full acceleration, zero Ka; no devices');return 0
    mode='stage' if a.prepare_off else 'restore' if a.restore_b_drive_off else 'run'
    name='ka-full-'+mode+'-'+str(time.time_ns())
    row=dict(mode=mode,pass_=False,receipt_path=str(TMP/(name+'.json')),steps=[],commands=[],uart=[],samples=[],postflight={},
        image_sha256=SHA,elf_sha256=ELF_SHA,baseline_restore_receipt=str(base.BASE_RESTORE_RECEIPT),
        physical_power_off=a.drive_off_unlocked_no_load_fixed,powered_no_alarm=a.operator_present_drive_on_no_alarm_05a,
        start_attempts=0,automatic_retry=False,automatic_parameter_write=False,friction_enabled=True,
        bemf_enabled=False,gain_percent=0,speed_target_rpm=240,speed_iq_limit_A=.50,overspeed_trip_rpm=300,
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
