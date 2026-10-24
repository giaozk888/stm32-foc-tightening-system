"""One supervised 240 rpm / 0.25 Ka startup-timestamp A test. FILES ONLY by default."""
import argparse
import hashlib
import json
import re
from pathlib import Path
import time
import accel_ff_gain_batch as gain
import startup_timestamps_report as startup

base=gain.base
TMP=base.TMP
ROOT_RESTORE=TMP/'accel-repeat025-restore-1792647859846346400.json'
IMAGE=base.old.ROOT/'foc2_app_a/build/StartupTimestampsDiagnostic/foc2.bin'
ELF=IMAGE.with_suffix('.elf')
SHA='c2fb66e8710f6ff92295cfe8201ce050173c1d96e9a7a598f0260ed393319108'
ELF_SHA='aa3b21194dff60e77ca7ea8c3ec1a65694d5487d6547851992b9169cf229a577'
SIZE=221716
GAIN_DECODE=gain.decode


def image():
    data=IMAGE.read_bytes()
    cmd=next(c['command'] for c in json.loads((IMAGE.parent/'compile_commands.json').read_text())
        if c['file'].endswith('/Core/Src/main.c'))
    required=('FOC_STARTUP_TIMESTAMPS_DIAG=1','FOC_ACCEL_FF_AUDIT=1','FOC_BEMF_ENABLED_DEFAULT=0',
        'FOC_CURRENT_PI_IDENTIFIED_ENABLE=1','FOC_ONE_CYCLE_PWM_PIPELINE=1',
        'FOC_PWM_PIPELINE_CLOSED_LOOP=1','FOC_INTENT_FSM_CANDIDATE=1',
        'FOC_FRICTION_ENABLED_DEFAULT=1','AS5047P_DMA_FOC_FIRST=1',
        'FOC_SPEED_PI_ANTI_WINDUP=1','FOC_ACCEL_FF_ENABLED_DEFAULT=1',
        'SPEED_FRICTION_I_A=0.105f','SPEED_ACCEL_FF_KA_A_PER_RPM_S=0.000046875f')
    if (len(data)!=SIZE or hashlib.sha256(data).hexdigest()!=SHA or
        hashlib.sha256(ELF.read_bytes()).hexdigest()!=ELF_SHA or
        base.hw.image_info(data)[0]!='A' or any('-D'+x+' ' not in cmd for x in required) or
        any('-D'+x in cmd for x in ('FOC_PSI_IDENT','FOC_DQ_DECOUPLING_CANDIDATE',
            'FOC_CURRENT_STEP_AB_DIAG','FOC_FAST_REJECT_COMPUTE_ONLY'))):
        raise ValueError('Exact offline-tested startup diagnostic BIN/ELF/flags required')
    sym=base.symbols(ELF)
    if sym.get('startup_timestamps',(0,0))[1]!=76 or sym.get('speed_accel_audit',(0,0))[1]!=1112:
        raise ValueError('Startup/audit RAM ABI mismatch')
    for marker in (b'MOTOR TEST FF STARTUP',b'MOTOR TEST FF GAIN ',b'TRIP_MA=4000',b'METHOD=TWO_SAMPLE',
        b'RUNDOWN240: RAM=240rpm TRIP=300rpm SAVE=OFF',b'TRAVEL=20000deg RAM only'):
        if marker not in data:raise ValueError('Diagnostic/protection marker missing')
    base.support.support.require_baud(cmd)
    return data


def motion(board,row):
    if row.get('gain_percent')!=25 or row.get('bemf_enabled') is not False:
        raise ValueError('Only 0.25 Ka with BEMF OFF is authorized; no START')
    try:gain.motion(board,row) # Existing idle-only gain readback + protected single START/STOP owner.
    finally:
        if row.get('start_attempts'):
            try:
                row['startup_reply']=board.command('MOTOR TEST FF STARTUP')
                row['startup_uart']=base.hw.fields(row['startup_reply'])
            except Exception as error:row['startup_query_error']=str(error)


def decode(row):
    GAIN_DECODE(row)
    gain.prior.checkpoint(row,'captured_before_startup_decode')
    row['startup_saved']=startup.decode(Path(row['receipt_path']),ELF)


def setup(path):
    # First prove B959 using the PREVIOUS exact A. Only then install the new verifier.
    gain.setup(ROOT_RESTORE)
    base.baseline()
    gain.IMAGE,gain.ELF,gain.SHA,gain.ELF_SHA,gain.SIZE=IMAGE,ELF,SHA,ELF_SHA,SIZE
    gain.image=image
    gain.fitted.IMAGE,gain.fitted.ELF,gain.fitted.SHA,gain.fitted.ELF_SHA,gain.fitted.SIZE=IMAGE,ELF,SHA,ELF_SHA,SIZE
    gain.fitted.image=image;gain.fitted.motion=motion;gain.fitted.decode=decode
    base.IMAGE,base.ELF,base.SHA,base.ELF_SHA=IMAGE,ELF,SHA,ELF_SHA
    base.image=image;base.motion=motion;base.decode_cm=decode
    if path.resolve()!=ROOT_RESTORE.resolve():base.configure_baseline(path)
    return image()


def classify(row):
    metrics=gain.metrics(row)
    saved=row['startup_saved'];s=saved['snapshot'];wire=row.get('startup_uart',{})
    mapping=dict(VALID='valid',T0_US='t0_us',TIQ_US='t_iq_us',TMOTION_US='t_motion_us',
        TSPEED_US='t_speed_us',TSTABLE_US='t_stable_us')
    if (row.get('startup_query_error') or s['valid']!=31 or
        any(wire.get(k)!=str(s[v]) for k,v in mapping.items()) or
        any(t is None or t>8_000_000 for t in saved['timings']['relative_to_t0'].values())):
        raise RuntimeError('Five startup events incomplete or UART/RAM mismatch; retain capture, no retry')
    metrics.update(startup_delays_ms={k:v/1000 for k,v in saved['timings']['relative_to_t0'].items()},
        motion_direction=s['motion_direction'],iq_at_event_a=s['iq_at_event_a'],
        speed_at_event_rpm=s['speed_at_event_rpm'])
    metrics['startup_log_seq']=check_logs(row)
    return metrics


def check_logs(row):
    groups={};s=row['startup_saved']['snapshot']
    for entry in row.get('tokenized_decoded',[]):
        line=entry['decoded'];match=re.search(r'STT ([ABCD]) seq=(\d+)',line)
        if match:
            groups.setdefault(match[2],{})[match[1]]=dict(re.findall(r'([a-z0-9_]+)=(-?[0-9.]+)',line))
    for seq,g in groups.items():
        if set(g)!=set('ABCD') or g['A'].get('valid')!='31':continue
        values={k:v for part in g.values() for k,v in part.items()}
        mapping=dict(t0_us='t0_us',tiq_us='t_iq_us',tmotion_us='t_motion_us',tspeed_us='t_speed_us',
            tstable_us='t_stable_us',motion_begin_us='motion_begin_us',motion_dir='motion_direction')
        if any(values.get(k)!=str(s[v]) for k,v in mapping.items()):continue
        if (abs(float(values['iq_at_event_a'])-s['iq_at_event_a'])>2e-6 or
            abs(float(values['speed_at_event_rpm'])-s['speed_at_event_rpm'])>2e-6):continue
        return int(seq)
    raise RuntimeError('Complete same-seq compressed startup log matching RAM absent; no fabricated timing')


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);m=p.add_mutually_exclusive_group()
    m.add_argument('--stage-off',action='store_true');m.add_argument('--execute-powered',type=Path)
    m.add_argument('--restore-b-drive-off',type=Path);p.add_argument('--baseline-restore',type=Path)
    p.add_argument('--drive-off-unlocked-no-load-fixed',action='store_true')
    p.add_argument('--operator-present-drive-on-no-alarm-05a',action='store_true');a=p.parse_args(argv)
    if (a.stage_off or a.restore_b_drive_off) and not a.drive_off_unlocked_no_load_fixed:p.error('Fresh drive OFF required')
    if a.execute_powered and not a.operator_present_drive_on_no_alarm_05a:p.error('Fresh supervised powered confirmation required')
    source=a.execute_powered or a.restore_b_drive_off
    selected=a.baseline_restore or (Path(json.loads(source.read_text())['baseline_restore_receipt']) if source else ROOT_RESTORE)
    data=setup(selected)
    if not (a.stage_off or source):print('OFFLINE PASS: one startup-timestamp test, 0.25 Ka; no devices');return 0
    mode='stage' if a.stage_off else 'restore' if a.restore_b_drive_off else 'run'
    name='startup-times-'+mode+'-'+str(time.time_ns())
    row=dict(mode=mode,pass_=False,receipt_path=str(TMP/(name+'.json')),steps=[],commands=[],uart=[],samples=[],
        postflight={},image_sha256=SHA,elf_sha256=ELF_SHA,baseline_restore_receipt=str(base.BASE_RESTORE_RECEIPT),
        friction_enabled=True,bemf_enabled=False,gain_percent=25,start_attempts=0,automatic_retry=False,
        physical_power_off=a.drive_off_unlocked_no_load_fixed,powered_no_alarm=a.operator_present_drive_on_no_alarm_05a,
        host_max_seconds=base.HOST_MAX_SECONDS,speed_target_rpm=240,speed_iq_limit_A=.50,overspeed_trip_rpm=300)
    gain.prior.checkpoint(row,'prepared')
    try:
        if a.stage_off:base.stage(row,name,data)
        elif a.restore_b_drive_off:base.restore(row,name,source,data)
        else:
            try:base.execute(row,name,source,data)
            except RuntimeError as error:
                if str(error)!=gain.EXPECTED_TERMINAL:raise
                row['natural_terminal_note']=str(error)
            row['metrics']=classify(row);row['acquisition_complete']=True;row['tightening_success']=False;row['pass_']=True
    except BaseException as error:
        row['failure']=str(error)
        if row.get('hardware_attempted') and not row.get('final_cpu_halted'):
            try:base.hw.emergency_off(row,TMP/(name+'-failed.bin'))
            except Exception as off:row['cleanup_error']=str(off)
    gain.prior.checkpoint(row,'complete' if row['pass_'] else 'stopped')
    print(('PASS: ' if row['pass_'] else 'STOPPED: ')+row['receipt_path'],flush=True)
    if row.get('failure'):print(row['failure'],flush=True)
    if row.get('metrics'):print(json.dumps(row['metrics'],indent=2),flush=True)
    return 0 if row['pass_'] else 1


if __name__=='__main__':raise SystemExit(main())
