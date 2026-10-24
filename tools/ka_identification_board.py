"""One supervised 240rpm Ka acquisition. FILES ONLY by default; no gain sweep."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import time
import startup_timestamps_board as previous
import ka_identification_report as identification

gain=previous.gain
base=previous.base
TMP=previous.TMP
ROOT_RESTORE=TMP/'startup-repeat-restore-1792650012377333500.json'
IMAGE=base.old.ROOT/'foc2_app_a/build/KaIdentificationDiagnostic/foc2.bin'
ELF=IMAGE.with_suffix('.elf')
SHA='cd9f970c4ddfb3ce8ddb9f2e13e1046441d5644bb05df01e493f726d570fb8be'
ELF_SHA='b8b587ac31cbebdc3901f75ee06c320236836bf956bcd39393568224775bc893'
SIZE=219828


def image():
    data=IMAGE.read_bytes()
    cmd=next(c['command'] for c in json.loads((IMAGE.parent/'compile_commands.json').read_text())
        if c['file'].endswith('/Core/Src/main.c'))
    required=('FOC_KA_IDENT_DIAG=1','FOC_BEMF_CANDIDATE=1','FOC_BEMF_ENABLED_DEFAULT=0',
        'FOC_BEMF_PSI_WB=0.00069732f','FOC_CURRENT_PI_IDENTIFIED_ENABLE=1',
        'FOC_ONE_CYCLE_PWM_PIPELINE=1','FOC_PWM_PIPELINE_CLOSED_LOOP=1',
        'FOC_INTENT_FSM_CANDIDATE=1','FOC_FRICTION_ENABLED_DEFAULT=1','AS5047P_DMA_FOC_FIRST=1',
        'FOC_SPEED_PI_ANTI_WINDUP=1','FOC_ACCEL_FF_ENABLED_DEFAULT=1',
        'SPEED_FRICTION_I_A=0.105f','SPEED_ACCEL_FF_KA_A_PER_RPM_S=0.0000000f')
    if (len(data)!=SIZE or hashlib.sha256(data).hexdigest()!=SHA or
        hashlib.sha256(ELF.read_bytes()).hexdigest()!=ELF_SHA or base.hw.image_info(data)[0]!='A' or
        any('-D'+d+' ' not in cmd for d in required) or
        any('-D'+d in cmd for d in ('FOC_STARTUP_TIMESTAMPS_DIAG','FOC_ACCEL_FF_AUDIT',
            'FOC_PSI_IDENT','FOC_DQ_DECOUPLING_CANDIDATE','FOC_CURRENT_STEP_AB_DIAG','FOC_FAST_REJECT_COMPUTE_ONLY')) or
        base.symbols(ELF).get('ka_identification',(0,0))[1]!=1032):
        raise ValueError('Exact offline-tested Ka BIN/ELF/flags/ABI required')
    for marker in (b'TRIP_MA=4000',b'METHOD=TWO_SAMPLE',
        b'RUNDOWN240: RAM=240rpm TRIP=300rpm SAVE=OFF',b'TRAVEL=20000deg RAM only'):
        if marker not in data:raise ValueError('Protection/profile marker missing')
    base.support.support.require_baud(cmd)
    return data


def motion(board,row):
    if row.get('gain_percent')!=0 or row.get('bemf_enabled') is not False or not row.get('friction_enabled'):
        raise ValueError('Only zero-Ka / fixed-friction / BEMF-OFF acquisition authorized')
    # No GAIN command: this candidate has a compile-time zero Ka. The original
    # idle/calibrated/profile/recipe/lease/protection/one-START owner is reused.
    gain.current_gain=0
    gain.ORIGINAL_MOTION(board,row)


def decode(row):
    gain.ORIGINAL_DECODE(row)
    gain.prior.checkpoint(row,'captured_before_ka_decode')
    row['ka_capture']=identification.decode(Path(row['receipt_path']),ELF)


def setup(path):
    # Prove the installed timestamp-A/B967 baseline using its OLD verifier,
    # then install the NEW identity. Never retag an old receipt with new hashes.
    previous.setup(ROOT_RESTORE);base.baseline()
    gain.IMAGE,gain.ELF,gain.SHA,gain.ELF_SHA,gain.SIZE=IMAGE,ELF,SHA,ELF_SHA,SIZE
    gain.image=image;gain.current_gain=0
    fitted=gain.fitted
    fitted.IMAGE,fitted.ELF,fitted.SHA,fitted.ELF_SHA,fitted.SIZE=IMAGE,ELF,SHA,ELF_SHA,SIZE
    fitted.image=image;fitted.motion=motion;fitted.decode=decode
    base.IMAGE,base.ELF,base.SHA,base.ELF_SHA=IMAGE,ELF,SHA,ELF_SHA
    base.image=image;base.motion=motion;base.decode_cm=decode
    if path.resolve()!=ROOT_RESTORE.resolve():base.configure_baseline(path)
    return image()


def check_logs(row):
    groups={}
    for entry in row.get('tokenized_decoded',[]):
        line=entry['decoded'];match=re.search(r'KAI ([TSI]) seq=(\d+)',line)
        if match:groups.setdefault(int(match[2]),{})[match[1]]=dict(re.findall(r'(\w+)=(-?[0-9.]+)',line))
    for f in row['ka_capture']['windows']:
        g=groups.get(f['seq'],{})
        if set(g)!=set('TSI'):raise RuntimeError('Incomplete same-seq KAI compressed log')
        wire={k:v for part in g.values() for k,v in part.items()}
        for k in ('start_us','end_us','flags'):
            if wire.get(k)!=str(f[k]):raise RuntimeError('KAI timestamp/flags mismatch')
        mapping=dict(speed_start='speed_start_rpm',speed_end='speed_end_rpm',
            ref='mean_speed_ref_rpm',meas='mean_speed_meas_rpm',iq_mean='mean_iq_a',fric_mean='mean_friction_a')
        if any(k not in wire or abs(float(wire[k])-f[v])>2e-6 for k,v in mapping.items()):
            raise RuntimeError('KAI measured current/speed/friction log vs RAM mismatch')
    return len(row['ka_capture']['windows'])


def classify(row):
    metrics=gain.prior.metrics(row) # Original full protection/timing/evidence classifier.
    saved=row['ka_capture']
    if saved['samples']<2400 or len(saved['windows'])!=24:raise RuntimeError('Incomplete Ka acquisition; no retry')
    if check_logs(row)!=24:raise RuntimeError('Missing KAI coverage')
    metrics['ka_compile_time']=0.0
    stats=row['accel_ff_ram_stats']
    metrics['accel_mae_rpm_full_precision']=stats['accel_error_integral']/stats['accel_time_s'] if stats['accel_time_s']>0 else None
    return metrics


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);m=p.add_mutually_exclusive_group()
    m.add_argument('--stage-off',action='store_true');m.add_argument('--execute-powered',type=Path)
    m.add_argument('--restore-b-drive-off',type=Path);p.add_argument('--baseline-restore',type=Path)
    p.add_argument('--drive-off-unlocked-no-load-fixed',action='store_true')
    p.add_argument('--operator-present-drive-on-no-alarm-05a',action='store_true');a=p.parse_args(argv)
    if (a.stage_off or a.restore_b_drive_off) and not a.drive_off_unlocked_no_load_fixed:p.error('Fresh OFF confirmation required')
    if a.execute_powered and not a.operator_present_drive_on_no_alarm_05a:p.error('Fresh powered/no-alarm/operator confirmation required')
    source=a.execute_powered or a.restore_b_drive_off
    selected=a.baseline_restore or (Path(json.loads(source.read_text())['baseline_restore_receipt']) if source else ROOT_RESTORE)
    data=setup(selected)
    if not (a.stage_off or source):print('OFFLINE PASS: zero-Ka measured acceleration/current acquisition; no devices');return 0
    mode='stage' if a.stage_off else 'restore' if a.restore_b_drive_off else 'run'
    name='ka-ident-'+mode+'-'+str(time.time_ns())
    row=dict(mode=mode,pass_=False,receipt_path=str(TMP/(name+'.json')),steps=[],commands=[],uart=[],samples=[],postflight={},
        image_sha256=SHA,elf_sha256=ELF_SHA,baseline_restore_receipt=str(base.BASE_RESTORE_RECEIPT),
        friction_enabled=True,bemf_enabled=False,gain_percent=0,start_attempts=0,automatic_retry=False,
        physical_power_off=a.drive_off_unlocked_no_load_fixed,powered_no_alarm=a.operator_present_drive_on_no_alarm_05a,
        speed_target_rpm=240,speed_iq_limit_A=.50,overspeed_trip_rpm=300,host_max_seconds=base.HOST_MAX_SECONDS,
        automatic_parameter_write=False)
    gain.prior.checkpoint(row,'prepared')
    try:
        if a.stage_off:base.stage(row,name,data)
        elif a.restore_b_drive_off:base.restore(row,name,source,data)
        else:
            try:base.execute(row,name,source,data)
            except RuntimeError as error:
                if str(error)!=gain.EXPECTED_TERMINAL:raise
                row['natural_terminal_note']=str(error)
            row['metrics']=classify(row)
            gain.prior.checkpoint(row,'accepted_before_ka_fit')
            row['ka_capture']=identification.decode(Path(row['receipt_path']),ELF)
            row['ka_fit']=identification.report(row['ka_capture'])
            row['acquisition_complete']=True;row['tightening_success']=False;row['pass_']=True
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
