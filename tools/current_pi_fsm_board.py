"""One supervised no-load original FSM run with new current PI. Files-only default.

No speed/current/voltage/protection increase, forced contact or automatic retry.
Separate drive-OFF inactive A stage, powered single START, drive-OFF B restore.
"""
import argparse
import json
from pathlib import Path
import time
import zlib

import friction_fsm_board as base

TMP=base.TMP
IMAGE=base.old.ROOT/'foc2_app_a/build/CurrentPiIdentifiedCandidate/foc2.bin'
ELF=IMAGE.with_suffix('.elf')
SHA='aaeee6b02372f9ecac2d8ec0ecb171f17bf87df41e54f43fe52b4ec9d404b56e'
ELF_SHA='d015db4a488cefb4d17af5d59631731163c22a54d14aa41baef91708f19c3b77'
RESTORE=TMP/'current-pi-fsm-restore-1792566834677593400.json'
BASE_SHA='52d67f8401b8eb1fec942b37dbc9f0c6a9a8250633d228629144f28662954ef2'
BASE_META=(1112493908,3,2,0,0,888,217428,4178387643,227964,627317606,0,1024768680)


def image():
    data=IMAGE.read_bytes()
    commands=json.loads((IMAGE.parent/'compile_commands.json').read_text('utf-8'))
    command=next(c['command'] for c in commands if c['file'].endswith('/Core/Src/main.c'))
    required=('FOC_CURRENT_PI_IDENTIFIED_ENABLE','FOC_PWM_PIPELINE_CLOSED_LOOP',
        'FOC_INTENT_FSM_CANDIDATE','FOC_ADC_COUNTS_100_40_CANDIDATE',
        'FOC_SPEED_PI_ANTI_WINDUP','FOC_SPEED_SB3_DISABLE_CANDIDATE','FOC_SPEED_SCURVE_CANDIDATE',
        'FOC_ACCEL_FEEDFORWARD_CANDIDATE','FOC_ACCEL_FF_ENABLED_DEFAULT',
        'FOC_SPEED_FRICTION_CANDIDATE','FOC_FRICTION_ENABLED_DEFAULT')
    if (len(data)!=217428 or base.old.zero.digest(data)!=SHA or
        base.old.zero.digest(ELF.read_bytes())!=ELF_SHA or base.hw.image_info(data)[0]!='A' or
        any(command.count('-D'+key+'=1')!=1 for key in required) or
        any(key in command for key in ('-DFOC_FAST_REJECT_COMPUTE_ONLY=1',
            '-DFOC_IDENT_VOLTAGE_STEP_DIAG=1','-DFOC_MOTOR_IDENTIFICATION_DIAG=1')) or
        any(flag not in command for flag in ('-DCURRENT_PI_CANDIDATE_BANDWIDTH_HZ=300.0f',
            '-DSPEED_FRICTION_I_A=0.105f','-DSPEED_ACCEL_FF_KA_A_PER_RPM_S=0.0001875f'))):
        raise ValueError('Exact offline-tested new current PI/FSM BIN/ELF required')
    for marker in (b'INTENT_FSM_CANDIDATE; manual START only',b'TRIP_MA=4000',
        b'RPM=240 LEASE_US=12000000',b'METHOD=TWO_SAMPLE',b'TRAVEL=20000deg RAM only'):
        if marker not in data:raise ValueError('Protected full-FSM marker missing')
    return data


def configure():
    r=json.loads(RESTORE.read_text('utf-8'));capture=Path(r.get('final_capture','')).resolve()
    if (capture.parent!=TMP.resolve() or r.get('mode')!='restore' or r.get('final_sha256')!=BASE_SHA or
        r.get('motor_commands')!=0 or any(r.get(k) is not True for k in
        ('pass_','all_app_private_unchanged','b_application_not_run','final_cpu_halted','final_outputs_off'))):
        raise ValueError('Exact B888 OFF restore receipt required')
    raw=capture.read_bytes();root=base.ROOT_BASE.read_bytes();off=r.get('outputs',{})
    if (len(raw)!=0x80000 or base.old.zero.digest(raw)!=BASE_SHA or
        tuple(base.old.zero.latest_meta(raw))!=BASE_META or list(BASE_META)!=r.get('metadata') or
        base.old.zero.digest(root)!=base.ROOT_BASE_SHA or raw[:0x8000]!=root[:0x8000] or
        raw[0x40000:0x7e800]!=root[0x40000:0x7e800] or raw[0x7f800:]!=root[0x7f800:] or
        zlib.crc32(raw[0x40000:0x40000+227964])!=627317606 or
        off.get('VTOR')!=0x08040000 or not off.get('DHCSR',0)&0x20000 or
        off.get('SD',0x40)&0x40 or off.get('BDTR',0xc000)&0xc000 or off.get('CCER',1)):
        raise ValueError('B888 Flash/boot/private/output proof mismatch')
    base.BASE=capture;base.BASE_SHA=BASE_SHA;base.EXPECT_META=BASE_META
    base.BASE_RESTORE_RECEIPT=RESTORE.resolve()
    base.IMAGE=IMAGE;base.ELF=ELF;base.SHA=SHA;base.ELF_SHA=ELF_SHA;base.image=image;base.FRICTION_A=.105


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);m=p.add_mutually_exclusive_group()
    m.add_argument('--stage-off',action='store_true');m.add_argument('--execute-powered',type=Path)
    m.add_argument('--restore-b-drive-off',type=Path)
    p.add_argument('--drive-off-unlocked-no-load-fixed',action='store_true')
    p.add_argument('--operator-present-drive-on-no-alarm-05a',action='store_true')
    a=p.parse_args(argv)
    if (a.stage_off or a.restore_b_drive_off) and not a.drive_off_unlocked_no_load_fixed:p.error('Fresh OFF/unlocked no-load fixture required')
    if a.execute_powered and not a.operator_present_drive_on_no_alarm_05a:p.error('Fresh ON/no-alarm supervised fixture required')
    configure();data=image();base.baseline()
    if not (a.stage_off or a.execute_powered or a.restore_b_drive_off):
        print('OFFLINE PASS: pinned new current PI, protected 240rpm/500mA FSM, B888; no devices');return 0
    kind='stage' if a.stage_off else 'run' if a.execute_powered else 'restore'
    name='current-pi-fsm-'+kind+'-'+str(time.time_ns())
    row=dict(mode=kind,pass_=False,receipt_path=str(TMP/(name+'.json')),steps=[],commands=[],uart=[],samples=[],postflight={},
        image_sha256=SHA,elf_sha256=ELF_SHA,baseline_restore_receipt=str(RESTORE),baseline_sha256=BASE_SHA,
        physical_power_off=a.drive_off_unlocked_no_load_fixed,powered_no_alarm=a.operator_present_drive_on_no_alarm_05a,
        start_attempts=0,automatic_retry=False,friction_enabled=True,friction_a=.105,
        current_pi='IDENTIFIED_300HZ',rs_ohm=.78,ld_h=20.03e-6,lq_h=11.18e-6,
        kp_d=.0377556644,kp_q=.0210738052,ki_d=1470.26538,ki_q=1470.26538,
        speed_target_rpm=240,speed_iq_limit_A=.5,overspeed_trip_rpm=300,max_travel_deg=20000,
        host_max_seconds=base.HOST_MAX_SECONDS,no_load=True,shaft_unlocked=True,
        parameter_identification_qualified=False,automatic_parameter_write=False)
    base.old.prior.checkpoint(row,'prepared')
    try:
        if a.stage_off:base.stage(row,name,data)
        elif a.execute_powered:base.execute(row,name,a.execute_powered,data)
        else:base.restore(row,name,a.restore_b_drive_off,data)
    except BaseException as error:
        row.update(pass_=False,failure=str(error))
        if row.get('hardware_attempted') and not row.get('final_cpu_halted'):
            try:base.hw.emergency_off(row,TMP/(name+'-failed.bin'))
            except Exception as off:row['cleanup_error']=str(off)
    base.old.prior.checkpoint(row,'complete' if row['pass_'] else 'stopped')
    print(('PASS: ' if row['pass_'] else 'STOPPED: ')+row['receipt_path'],flush=True)
    if row.get('failure'):print(row['failure'],flush=True)
    return 0 if row['pass_'] else 1


if __name__=='__main__':raise SystemExit(main())
