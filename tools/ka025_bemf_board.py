"""Normal Ka=.000046875 A, one explicit BEMF OFF or ON run. Files-only default."""
import argparse
import hashlib
import json
from pathlib import Path
import time
import ka279_board as previous

base=previous.base;gain=previous.gain;TMP=previous.TMP
ROOT_RESTORE=TMP/'ka279-repeat-restore-1792660747794505000.json'
KA=.000046875
IMAGE=base.old.ROOT/'foc2_app_a/build/TighteningKa025Candidate/foc2.bin'
ELF=IMAGE.with_suffix('.elf')
SHA='4236aa0f7234b43bb12b6254fab0c75b34e59fc7ad8261be808f5a4b9054400a'
ELF_SHA='14d6ba34f4a66755d73fb174994f23beb0b3f51e23acb617cbf73b937efcd377'
SIZE=211584

def image():
    data=IMAGE.read_bytes()
    cmd=next(x['command'] for x in json.loads((IMAGE.parent/'compile_commands.json').read_text())
             if x['file'].endswith('/Core/Src/main.c'))
    defines=('FOC_BEMF_CANDIDATE=1','FOC_BEMF_ENABLED_DEFAULT=0','FOC_BEMF_PSI_WB=0.00069732f',
        'SPEED_ACCEL_FF_KA_A_PER_RPM_S=0.000046875f','SPEED_FRICTION_I_A=0.105f',
        'FOC_CURRENT_PI_IDENTIFIED_ENABLE=1','FOC_PROTECTED_CLOSED_LOOP=1',
        'FOC_ONE_CYCLE_PWM_PIPELINE=1','FOC_PWM_PIPELINE_CLOSED_LOOP=1',
        'FOC_INTENT_FSM_CANDIDATE=1','FOC_SPEED_PI_ANTI_WINDUP=1','AS5047P_DMA_FOC_FIRST=1',
        'FOC_ACCEL_FF_ENABLED_DEFAULT=1','FOC_FRICTION_ENABLED_DEFAULT=1','PW_LOG_STORE_CAPACITY=48')
    if (len(data)!=SIZE or hashlib.sha256(data).hexdigest()!=SHA or
        hashlib.sha256(ELF.read_bytes()).hexdigest()!=ELF_SHA or base.hw.image_info(data)[0]!='A' or
        any('-D'+x+' ' not in cmd for x in defines) or
        any('-D'+x in cmd for x in ('FOC_ACCEL_FF_AUDIT','FOC_KA_FULL_DIAG','FOC_KA_SYNC_DIAG',
            'FOC_KA_IDENT_DIAG','FOC_PSI_IDENT','FOC_DQ_DECOUPLING_CANDIDATE','FOC_FAST_REJECT_COMPUTE_ONLY'))):
        raise ValueError('Exact normal Ka025 BEMF-OFF image/ELF required')
    for marker in (b'METHOD=TWO_SAMPLE',b'TRIP_MA=4000',b'TRAVEL=20000deg RAM only',
                   b'RUNDOWN240: RAM=240rpm TRIP=300rpm SAVE=OFF'):
        if marker not in data:raise ValueError('Safety/profile marker missing')
    base.support.support.require_baud(cmd);return data

def ff_status(line):
    v=base.hw.fields(line)
    expected=dict(ON='1',KA_NA_PER_RPM_S='46875',ACCEL_MAX_RPM_S='200',FF_PEAK_UA='9375',TOKENIZED='1')
    if any(v.get(k)!=x for k,x in expected.items()):raise RuntimeError('Exact normal 0.25-Ka required')
    return v

def friction_status(line,enabled):
    v=base.hw.fields(line)
    expected=dict(ON=str(int(enabled)),I_UA='105000',DB_MRPM='2000',FF_ON='1',KA_NA_PER_RPM_S='46875',TOKENIZED='1')
    if any(v.get(k)!=x for k,x in expected.items()):raise RuntimeError('Fixed friction/Ka025 required')
    return v

def motion(board,row):
    if row.get('manual_ka')!=KA or not row.get('friction_enabled') or row.get('bemf_enabled') not in (False,True):
        raise ValueError('Exact normal Ka025 and explicit BEMF choice required')
    gain.ORIGINAL_MOTION(board,row) # Existing idle BEMF toggle, protected single START, no GAIN.

def setup(path):
    previous.setup(ROOT_RESTORE);base.baseline() # Prove real B995 and old image first.
    for obj in (base,gain,gain.fitted):
        obj.IMAGE,obj.ELF,obj.SHA,obj.ELF_SHA=IMAGE,ELF,SHA,ELF_SHA;obj.image=image
    gain.SIZE=SIZE;gain.fitted.SIZE=SIZE
    base.motion=motion;gain.fitted.motion=motion
    base.decode_cm=gain.ORIGINAL_DECODE;gain.fitted.decode=gain.ORIGINAL_DECODE
    base.ff_status=ff_status;base.friction_status=friction_status
    if path.resolve()!=ROOT_RESTORE.resolve():base.configure_baseline(path)
    return image()

def execute(row,name,plan,data):
    staged=json.loads(plan.read_text())
    if staged.get('bemf_enabled') is not row['bemf_enabled']:
        raise ValueError('Runtime BEMF choice differs from staged plan')
    try:base.execute(row,name,plan,data)
    except RuntimeError as error:
        if str(error)!=gain.EXPECTED_TERMINAL:raise
        row['natural_terminal_note']=str(error)
    row['metrics']=gain.prior.metrics(row)
    row['metrics'].update(manual_ka=KA,bemf_enabled=row['bemf_enabled'])
    row.update(pass_=True,acquisition_complete=True,tightening_success=False)

def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);m=p.add_mutually_exclusive_group()
    m.add_argument('--prepare-off',action='store_true');m.add_argument('--execute-powered',type=Path)
    m.add_argument('--restore-b-drive-off',type=Path);p.add_argument('--baseline-restore',type=Path)
    p.add_argument('--bemf-on',action='store_true')
    p.add_argument('--drive-off-unlocked-no-load-fixed',action='store_true')
    p.add_argument('--operator-present-drive-on-no-alarm-05a',action='store_true');a=p.parse_args(argv)
    if (a.prepare_off or a.restore_b_drive_off) and not a.drive_off_unlocked_no_load_fixed:p.error('Fresh OFF required')
    if a.execute_powered and not a.operator_present_drive_on_no_alarm_05a:p.error('Fresh supervised powered confirmation required')
    source=a.execute_powered or a.restore_b_drive_off
    selected=a.baseline_restore or (Path(json.loads(source.read_text())['baseline_restore_receipt']) if source else ROOT_RESTORE)
    data=setup(selected)
    if not(a.prepare_off or source):print('OFFLINE PASS: normal Ka025, explicit BEMF choice; no devices');return 0
    mode='stage' if a.prepare_off else 'restore' if a.restore_b_drive_off else 'run'
    name='ka025-bemf-'+mode+'-'+str(time.time_ns())
    row=dict(mode=mode,pass_=False,receipt_path=str(TMP/(name+'.json')),steps=[],commands=[],uart=[],
        samples=[],postflight={},image_sha256=SHA,elf_sha256=ELF_SHA,
        baseline_restore_receipt=str(base.BASE_RESTORE_RECEIPT),physical_power_off=a.drive_off_unlocked_no_load_fixed,
        powered_no_alarm=a.operator_present_drive_on_no_alarm_05a,start_attempts=0,automatic_retry=False,
        automatic_parameter_write=False,manual_ka=KA,friction_enabled=True,bemf_enabled=a.bemf_on,
        speed_target_rpm=240,speed_iq_limit_A=.50,overspeed_trip_rpm=300,host_max_seconds=base.HOST_MAX_SECONDS)
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
