"""Pinned DQA1 nominal-sign A. Default files only; separate OFF stage/run/restore.

Reuses reviewed stop/lease/protection/boot owners, not the obsolete image pins.
One manual START maximum, no retries, no reverse-sign/automatic batch execution.
"""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import time
import zlib
import dq_decoupling_fsm_board as prior
import dq_decoupling_audit_report as report

base=prior.base
TMP=base.TMP
ROOT=base.old.ROOT
IMAGE=ROOT/'foc2_app_a/build/DqAuditCurrent/foc2.bin'
ELF=IMAGE.with_suffix('.elf')
SHA='82ade68937f2dc0420a48fdaf10d811042447b78101d6bd553227578587e0627'
ELF_SHA='8fec71f92f29d6fb499d3f3b8186ec36429a01f460340f800e30061f1fbad0e3'
ROOT_RECEIPT=TMP/'dq-fsm-restore-1792579402223585900.json'
ROOT_SHA='464aae9dd445156eda51ce39ff2d148bfe50759ff4da0d56e28de05c0f3848f9'


def digest(data):return hashlib.sha256(data).hexdigest()


def image():
    data=IMAGE.read_bytes()
    if (len(data)!=221100 or digest(data)!=SHA or digest(ELF.read_bytes())!=ELF_SHA or
        base.hw.image_info(data)[0]!='A'):
        raise ValueError('Exact tested nominal DQA1 A BIN/ELF required')
    cmd=next(c['command'] for c in json.loads((IMAGE.parent/'compile_commands.json').read_text())
             if c['file'].endswith('/Core/Src/main.c'))
    base.support.support.require_baud(cmd)
    for flag in ('FOC_DQ_AUDIT_ENABLE=1','DECOUPLING_SIGN_TEST=1','DECOUPLING_SIGN_MODE=0',
        'FOC_DQ_DECOUPLING_CANDIDATE=1','FOC_DQ_DECOUPLING_ENABLED_DEFAULT=1',
        'FOC_DQ_LD_H=0.00002003f','FOC_DQ_LQ_H=0.00001118f',
        'FOC_ONE_CYCLE_PWM_PIPELINE=1','FOC_PWM_PIPELINE_CLOSED_LOOP=1',
        'FOC_INTENT_FSM_CANDIDATE=1','FOC_SPEED_PI_ANTI_WINDUP=1',
        'FOC_SPEED_SB3_DISABLE_CANDIDATE=1','FOC_SPEED_SCURVE_CANDIDATE=1',
        'FOC_ACCEL_FEEDFORWARD_CANDIDATE=1','FOC_ACCEL_FF_ENABLED_DEFAULT=1',
        'FOC_SPEED_FRICTION_CANDIDATE=1','FOC_FRICTION_ENABLED_DEFAULT=1',
        'SPEED_FRICTION_I_A=0.105f','SPEED_ACCEL_FF_KA_A_PER_RPM_S=0.0001875f',
        'FOC_CURRENT_PI_IDENTIFIED_ENABLE=1','CURRENT_PI_CANDIDATE_BANDWIDTH_HZ=300.0f',
        'AS5047P_DMA_FOC_FIRST=1','FOC_HEAVY_PROFILE_ENABLE=0'):
        if ('-D'+flag+' ') not in cmd:raise ValueError('Missing pinned unchanged option: '+flag)
    for forbidden in ('FOC_TORQUE_CHAIN_DIAG','FOC_CURRENT_STEP_AB_DIAG',
                      'FOC_MOTOR_IDENTIFICATION_DIAG','FOC_FAST_REJECT_COMPUTE_ONLY'):
        if '-D'+forbidden+'=1' in cmd:raise ValueError('Wrong control diagnostic')
    for marker in (b'TRIP_MA=4000',b'RPM=240 LEASE_US=12000000',b'METHOD=TWO_SAMPLE',
                   b'TRAVEL=20000deg RAM only',b'INTENT_FSM_CANDIDATE; manual START only',
                   b'OK DQA VERSION=1 SIGN_TEST='):
        if marker not in data:raise ValueError('Missing normal candidate/protection marker')
    syms=base.symbols(ELF)
    if syms['dq_audit'][1]!=148 or syms['dq_decoupling_frame'][1]!=56:
        raise ValueError('DQA1 SRAM schema mismatch')
    if b'DQA R seq=' in data or b'DQA R seq=' not in ELF.read_bytes():
        raise ValueError('Tokenized dictionary placement mismatch')
    return data


def configure(path):
    path=path.resolve()
    if path.parent!=TMP.resolve():raise ValueError('Private restored-B receipt required')
    r=json.loads(path.read_text());capture=Path(r.get('final_capture','')).resolve()
    if (capture.parent!=TMP.resolve() or r.get('mode')!='restore' or r.get('motor_commands')!=0 or
        any(r.get(k) is not True for k in ('pass_','all_app_private_unchanged',
            'b_application_not_run','final_cpu_halted','final_outputs_off'))):
        raise ValueError('Successful halted B restoration proof required')
    root_r=json.loads(ROOT_RECEIPT.read_text());root=Path(root_r['final_capture']).read_bytes()
    raw=capture.read_bytes();meta=base.old.zero.latest_meta(raw);off=r.get('outputs',{})
    if (len(root)!=0x80000 or digest(root)!=ROOT_SHA or len(raw)!=0x80000 or
        digest(raw)!=r.get('final_sha256') or list(meta)!=r.get('metadata') or
        meta[2:5]!=(2,0,0) or meta[8:10]!=(227964,627317606) or
        raw[:0x8000]!=root[:0x8000] or raw[0x40000:0x7e800]!=root[0x40000:0x7e800] or
        raw[0x7f800:]!=root[0x7f800:] or zlib.crc32(raw[0x40000:0x40000+meta[8]])!=meta[9] or
        off.get('VTOR')!=0x08040000 or not off.get('DHCSR',0)&0x20000 or
        off.get('SD',0x40)&0x40 or off.get('BDTR',0xc000)&0xc000 or off.get('CCER',1)):
        raise ValueError('B/boot/private/meta/halt/OFF identity mismatch')
    if path==ROOT_RECEIPT.resolve():
        if digest(raw)!=ROOT_SHA or meta[5]!=916:raise ValueError('Exact B916 root required')
    else:
        data=image()
        if (r.get('image_sha256')!=SHA or r.get('elf_sha256')!=ELF_SHA or meta[5]<=916 or
            meta[6:8]!=(len(data),zlib.crc32(data)) or raw[0x8000:0x8000+len(data)]!=data):
            raise ValueError('Exact same-audit restored B required')
    base.BASE=capture;base.BASE_SHA=digest(raw);base.EXPECT_META=meta;base.BASE_RESTORE_RECEIPT=path
    base.IMAGE=IMAGE;base.ELF=ELF;base.SHA=SHA;base.ELF_SHA=ELF_SHA;base.image=image
    base.FRICTION_A=.105;base.motion=motion;base.decode_cm=decode
    base.TokenRecordedBoard=prior.ORIGINAL_BOARD  # Token decode, no alternating UART queries.


def audit_status(line):
    f=base.hw.fields(line)
    for k,v in dict(VERSION='1',SIGN_TEST='1',MODE='0',LD_NH='20030',LQ_NH='11180',
                    LOG_US='100000',START_US='500000',STATIONARY_MRPM='1000').items():
        if f.get(k)!=v:raise RuntimeError('Audit formula/schema readback mismatch; no START')
    if ' OK DQA ' not in ' '+line:raise RuntimeError('Audit reply not acknowledged')
    return f


def motion(board,row):
    row['dq_audit_status']=audit_status(board.command('MOTOR TEST DQ AUDIT STATUS'))
    row['dq_switch']=prior.dq_status(board.command('MOTOR TEST DQ '+('ON' if row['dq_enabled'] else 'OFF')),
                                   row['dq_enabled'])
    row['dq_before']=prior.dq_status(board.command('MOTOR TEST DQ STATUS'),row['dq_enabled'])
    prior.ORIGINAL_MOTION(board,row)  # Unchanged preflight, original START, stop/lease/guards.


def decode(row):
    prior.ORIGINAL_DECODE(row)
    row['ram_sha256']=digest(Path(row['ram_capture']).read_bytes())
    # Adapt existing proven capture names to the offline DQA1 evidence schema.
    view=dict(row,flash_capture=row['final_capture'],vtor=row['outputs']['VTOR'])
    row['dq_audit_evidence']=report.evidence(view,ELF)
    row['dq_capture_semantics']='same-seq compressed task frames plus full accepted-frame SRAM aggregate; no sparse alternating queries'
    try:row['encoder_saved']=prior.encoder_report.decode_saved(row,ELF)
    except (ValueError,KeyError) as e:row['encoder_decode_error']=str(e)


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);m=p.add_mutually_exclusive_group()
    m.add_argument('--stage-off',action='store_true');m.add_argument('--execute-powered',type=Path)
    m.add_argument('--restore-b-drive-off',type=Path)
    p.add_argument('--baseline-restore',type=Path);p.add_argument('--dq-on',action='store_true')
    p.add_argument('--drive-off-unlocked-no-load-fixed',action='store_true')
    p.add_argument('--operator-present-drive-on-no-alarm-05a',action='store_true')
    a=p.parse_args(argv)
    if (a.stage_off or a.restore_b_drive_off) and not a.drive_off_unlocked_no_load_fixed:
        p.error('Fresh drive-OFF/unlocked/no-load/fixed confirmation required')
    if a.execute_powered and not a.operator_present_drive_on_no_alarm_05a:
        p.error('Fresh powered/no-alarm/operator-present/05A confirmation required')
    data=image();source_path=a.execute_powered or a.restore_b_drive_off
    source=json.loads(source_path.read_text()) if source_path else None
    selected=a.baseline_restore or (Path(source['baseline_restore_receipt']) if source else ROOT_RECEIPT)
    configure(selected);base.baseline()
    if not (a.stage_off or a.execute_powered or a.restore_b_drive_off):
        print('OFFLINE PASS: exact DQA1 A/B916, actual build flags and ABI; no devices');return 0
    if source is not None and source.get('dq_enabled')!=a.dq_on:
        raise ValueError('Staged/run DQ setting differs')
    kind='stage' if a.stage_off else 'run' if a.execute_powered else 'restore'
    name='dq-audit-'+kind+'-'+str(time.time_ns())
    row=dict(mode=kind,pass_=False,receipt_path=str(TMP/(name+'.json')),steps=[],commands=[],uart=[],
        samples=[],postflight={},image_sha256=SHA,elf_sha256=ELF_SHA,
        baseline_restore_receipt=str(selected.resolve()),baseline_sha256=base.BASE_SHA,
        physical_power_off=a.drive_off_unlocked_no_load_fixed,
        powered_no_alarm=a.operator_present_drive_on_no_alarm_05a,
        no_load=True,shaft_unlocked=True,start_attempts=0,automatic_retry=False,
        friction_enabled=True,friction_a=.105,dq_enabled=a.dq_on,sign_mode=0,
        ld_h=.00002003,lq_h=.00001118,speed_target_rpm=240,speed_iq_limit_A=.5,
        overspeed_trip_rpm=300,host_max_seconds=base.HOST_MAX_SECONDS,automatic_parameter_write=False)
    base.old.prior.checkpoint(row,'prepared')
    try:
        if a.stage_off:base.stage(row,name,data)
        elif a.execute_powered:base.execute(row,name,a.execute_powered,data)
        else:base.restore(row,name,a.restore_b_drive_off,data)
    except BaseException as e:
        row.update(pass_=False,failure=str(e))
        if row.get('hardware_attempted') and not row.get('final_cpu_halted'):
            try:base.hw.emergency_off(row,TMP/(name+'-failed.bin'))
            except Exception as off:row['cleanup_error']=str(off)
    base.old.prior.checkpoint(row,'complete' if row['pass_'] else 'stopped')
    print(('PASS: ' if row['pass_'] else 'STOPPED: ')+row['receipt_path'],flush=True)
    if row.get('failure'):print(row['failure'],flush=True)
    return 0 if row['pass_'] else 1


if __name__=='__main__':raise SystemExit(main())
