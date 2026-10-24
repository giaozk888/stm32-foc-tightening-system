"""One exact +450mA/5s/150rpm manual IQ comparison; offline default, no retries or ramp.

OFF staging only writes inactive A; powered execution is a separate operation.
All evidence stays local. A normal stop does not certify continuous rotation.
"""
import argparse
import json
import math
from pathlib import Path
import re
import statistics
import struct
import time
import zlib
import speed500_dynamic_acceptance as previous
import breakaway_current_report as report
import rundown_startup_decode as startup
from foc_path_profile_report import symbols

old=previous.old; hw=previous.hw; TMP=previous.TMP
IMAGE=old.ROOT/'foc2_app_a/build/Torque450mA150rpmFiveSecondDiagnostic/foc2.bin'
ELF=IMAGE.with_suffix('.elf')
SHA='c78296a6028ca5737ad8fd6159fb1b06214c40d4dc967463257477510d4b9433'
ELF_SHA='3d5ef30a01a82106dab164167fc6bae19ab19bb7f215123477725dfa86da44cc'
BASE=TMP/'torque450-restore-1792408452283540300-flash.bin'
BASE_SHA='935dc2b6aa1657ccfbbf6832e12c6123ba814fbf63cb1da840660f54e09931b8'
HOST_BAUD=115200
STATUS='MOTOR TEST TORQUE450 STATUS'
COMMAND='MOTOR TEST TORQUE450 CONFIRM'


def image():
    commands=json.loads((IMAGE.parent/'compile_commands.json').read_text('utf-8'))
    main=next(c['command'] for c in commands if c['file'].endswith('/Core/Src/main.c'))
    require_baud(main)
    if main.count('-DFOC_TORQUE450_150RPM=1')!=1:
        raise ValueError('Exact scoped 150rpm definition required')
    data=IMAGE.read_bytes()
    if (len(data)!=222532 or old.zero.digest(data)!=SHA or old.zero.digest(ELF.read_bytes())!=ELF_SHA or
            hw.image_info(data)[0]!='A'): raise ValueError('Exact tested 450mA BIN/ELF required')
    for marker in (b'IQ_MA=450 LIMIT_MA=450 ID_MA=0 LEASE_US=5000000',COMMAND.encode(),
                   b'TRIP_MA=4000',b'METHOD=TWO_SAMPLE',b'RPM_LIMIT=150'):
        if marker not in data: raise ValueError('Fixed IQ/lease/protection identity missing')
    if symbols(ELF)['breakaway_motion'][1]!=report.MOTION.size: raise ValueError('Motion ABI mismatch')
    return data


def require_baud(command):
    if re.findall(r'-DUART_LOG_BAUD=(\d+)\b',command)!=[str(HOST_BAUD)]:
        raise ValueError('Firmware/host baud mismatch; no device access')


def open_port():
    import serial
    port=serial.Serial(port=None,baudrate=HOST_BAUD,timeout=.02,write_timeout=2)
    port.dtr=port.rts=False; port.port='COM5'; port.open()
    return port


def baseline():
    """Exact restored B721 after the preceding 60rpm overspeed stop."""
    raw=BASE.read_bytes(); meta=old.zero.latest_meta(raw)
    if (len(raw)!=0x80000 or old.zero.digest(raw)!=BASE_SHA or meta[2:6]!=(2,0,0,721) or
            meta[6:10]!=(222516,2645259405,227964,627317606) or
            zlib.crc32(raw[0x40000:0x40000+meta[8]])!=meta[9]):
        raise ValueError('Exact halted B721 preservation baseline required')
    return raw


def stage(row,name,data):
    if row.get('physical_power_off') is not True: raise ValueError('Fresh drive OFF required')
    before=baseline(); dest=TMP/(name+'-staged.bin'); row['hardware_attempted']=True
    old.prior.checkpoint(row,'inactive_A_program_intent')
    output=hw.debug(row,[*old.zero.off_gate(),
        'if {[mrw 0xE000ED08] != 0x08040000} {error "Expected halted preserved B721"}',
        *hw.full_compare_commands(TMP/(name+'-before.bin'),BASE),
        'reset halt',*hw.off_commands(),
        f'flash write_image erase {{{IMAGE.as_posix()}}} 0x08008000 bin',
        f'verify_image {{{IMAGE.as_posix()}}} 0x08008000 bin',
        f'dump_image {{{dest.as_posix()}}} 0x08000000 0x80000',*hw.off_report(),'halt','shutdown'])
    raw=dest.read_bytes(); old.zero.validate_staged(raw,before,data)
    hw.debug(row,[*old.zero.off_gate(),
        *hw.full_compare_commands(TMP/(name+'-independent.bin'),dest),
        f'verify_image {{{IMAGE.as_posix()}}} 0x08008000 bin','halt','shutdown'])
    row.update(pass_=True,staged_capture=str(dest),staged_sha256=old.zero.digest(raw),
        outputs=hw.check_off(output,(0,0x08000000)),metadata=list(old.zero.latest_meta(raw)),
        activation=False,motor_commands=0,b_boot_private_metadata_unchanged=True,
        independent_readback_pass=True,final_cpu_halted=True,final_outputs_off=True)


def staged_input(path,data):
    r=json.loads(path.read_text('utf-8')); capture=Path(r.get('staged_capture','')).resolve()
    if (path.resolve().parent!=TMP.resolve() or capture.parent!=TMP.resolve() or
            r.get('mode')!='stage' or r.get('pass_') is not True or r.get('image_sha256')!=SHA or
            r.get('elf_sha256')!=ELF_SHA or r.get('physical_power_off') is not True or
            r.get('independent_readback_pass') is not True): raise ValueError('Exact OFF stage receipt required')
    raw=capture.read_bytes()
    if old.zero.digest(raw)!=r.get('staged_sha256'): raise ValueError('Stage capture changed')
    before=baseline()
    old.zero.validate_staged(raw,before,data)
    return capture,raw


class TorqueConsole(old.prior.JournalConsole):
    def torque(self,command,timeout=1.0):
        if command not in (STATUS,COMMAND): raise ValueError('Only fixed positive 450mA command/status')
        if command==COMMAND:
            if self.row.get('start_attempts'): raise RuntimeError('No repeat motion or ACK retry')
            self.row['start_attempts']=1; old.prior.checkpoint(self.row,'fixed_iq_start_intent')
        self.request+=1; request=self.request
        self.row['commands'].append(dict(command=command,at=time.monotonic()))
        self.port.write(f'{request} {command}\r\n'.encode('ascii'))
        until=time.monotonic()+timeout
        while time.monotonic()<until:
            line=self.read_line(.02)
            if line is None: continue
            self.dispatch(line)
            if line.startswith(f'{request} '):
                if not line.startswith(f'{request} OK '): raise RuntimeError(line)
                return line
        raise TimeoutError('Unknown command result; never resend')


def analyze(row):
    raw=Path(row['final_capture']).read_bytes(); ram=Path(row['ram_capture']).read_bytes()
    if (old.zero.digest(raw)!=row.get('final_sha256') or raw[0x8000:0x8000+len(image())]!=image() or
            row.get('outputs',{}).get('VTOR')!=0x08008000): raise ValueError('Capture identity mismatch')
    trace=startup.decode(startup.extract(ELF,ram,0x20000000,'arm-none-eabi-nm'),period_us=200000)
    trace['interpretation']=[x.replace('20Hz','5Hz').replace('sub-50ms','sub-200ms') for x in trace['interpretation']]
    trace['capture_identity_verified']=True; row['trace']=trace
    addr,size=symbols(ELF)['breakaway_motion']
    if size!=report.MOTION.size: raise ValueError('Wrong full-window motion layout')
    motion=dict(zip(report.MOTION_NAMES,report.MOTION.unpack_from(ram,addr-0x20000000)))
    row['full_window_motion']=motion
    rows=trace['rows']; tail=[r for r in rows if r['us']>=3333333]
    summary=dict(iq_ref_A=.45,IdRef_A=0,recorded_frames=len(rows),
        full_window_samples=motion['count'],net_travel_deg=motion['net_counts']*360/16384,
        tail_net_travel_deg=motion['tail_net_counts']*360/16384,
        raw_encoder_absolute_travel_deg=motion['absolute_counts']*360/16384,
        raw_encoder_jitter_included=True,physical_torque_or_speed_certified=False)
    if rows:
        for key in ('IqRef_A','Iq_A','Id_A','speed_ctrl_rpm','speed_instant_rpm','Vd_V','Vq_V'):
            v=[r[key] for r in rows]
            summary[key]=dict(mean=statistics.mean(v),mean_abs=statistics.mean(abs(x) for x in v),min=min(v),max=max(v))
        summary['tail_snapshot_mean_speed_rpm']=statistics.mean(r['speed_ctrl_rpm'] for r in tail) if tail else None
    summary['full_window_valid']=bool(motion['count']>=4000 and
        motion['last_us']-motion['first_us']>=4800000 and motion['max_gap_us']<=20000 and
        not any(motion[k] for k in ('bad_ref','bad_gates','bad_encoder')))
    summary['continuous_rotation_verified']=False  # Requires evidence interpretation, never just normal STOP.
    row['motion_summary']=summary


def execute(row,name,path,data):
    staged,before=staged_input(path,data); port=open_port(); uart=TorqueConsole(port,row)
    try:
        row['hardware_attempted']=True; old.prior.checkpoint(row,'trial_intent_no_motion')
        hw.debug(row,[*old.zero.off_gate(),*hw.full_compare_commands(TMP/(name+'-before.bin'),staged),
            'reset halt',*hw.off_commands(),
            *hw.write_mailbox(previous.mailbox(2,2,1,len(data),zlib.crc32(data))),'reset run','shutdown'])
        old.prior.wait_health_confirmation(uart,row,hw.fields)
        row['zero']=old.zero.zero_fields(uart.query('MOTOR TEST ZERO'))
        previous.prior.expect(hw.fields(uart.query('MOTOR TEST PROFILE')),
            dict(LEASE_US='5000000',SPEED_CTRL='SB3',VLIMIT_MV='1600'),'Protected 5s profile')
        row['torque_preflight']=hw.fields(uart.torque(STATUS))
        previous.prior.expect(row['torque_preflight'],dict(IQ_MA='450',LIMIT_MA='450',ID_MA='0',
            LEASE_US='5000000',PERIOD_US='200000',RPM_LIMIT='150',USED='0',ACTIVE='0',DENIED='0'),'Fixed IQ identity')
        previous.prior.expect(hw.fields(uart.query('MOTOR TEST PROTECTION')),
            dict(TRIP_MA='4000',STATE='0',REASON='0',FLAGS='0'),'Protection')
        old.prior.wait_timing(uart,row); previous.prior.standstill(uart,'1'); row['preflight_pass']=True
        row['start_ack']=uart.torque(COMMAND)
        until=time.monotonic()+5.3
        while time.monotonic()<until: uart.poll(min(.05,until-time.monotonic()))
        row['post_state']=previous.prior.off_state(uart,'3')
        previous.prior.expect(hw.fields(uart.torque(STATUS)),dict(USED='1',ACTIVE='0',DENIED='0'),'Pulse ended')
    finally:
        if row.get('hardware_attempted'):
            try: row['stop_ack']=uart.query('STOP',.6); row['safe_ack']=uart.query('ANALOG SAFE',.6)
            except Exception as error: row['stop_error']=str(error)
        if port.is_open: port.close()
        if row.get('hardware_attempted'): old.capture_stopped(row,name,before,elf=ELF)
    analyze(row)
    timing=row['snapshot']['timing']; fault=row['snapshot']['first_fault']
    row['pass_']=bool(row.get('preflight_pass') and row.get('start_attempts')==1 and not row.get('stop_error') and
        not fault['valid'] and 0<timing['wall_max_us']<50 and not timing['deadline_miss'] and
        not timing['actual_late_count'] and timing['actual_margin_min_us']>1 and
        row['motion_summary']['full_window_valid'] and row.get('final_outputs_off') and row.get('final_cpu_halted'))
    if any(r['mode']!=3 or r['gates']!=3 or abs(r['IqRef_A']-.45)>1e-6 for r in row['trace']['rows']):
        raise RuntimeError('Captured command was not fixed +450mA IQ mode')


def restore(row,name,path,data):
    if row.get('physical_power_off') is not True: raise ValueError('Fresh drive OFF required')
    r=json.loads(path.read_text('utf-8')); expected=Path(r.get('final_capture','')).resolve()
    if (path.resolve().parent!=TMP.resolve() or expected.parent!=TMP.resolve() or r.get('mode')!='run' or
            r.get('image_sha256')!=SHA or r.get('elf_sha256')!=ELF_SHA or any(r.get(k) is not True for k in
            ('final_cpu_halted','final_outputs_off','all_app_private_unchanged'))): raise ValueError('Exact stopped receipt')
    before=expected.read_bytes(); base=baseline(); meta=old.zero.latest_meta(before)
    if (old.zero.digest(before)!=r.get('final_sha256') or before[0x8000:0x8000+len(data)]!=data or
            meta[2:5]!=(1,0,0) or meta[6:8]!=(len(data),zlib.crc32(data)) or
            before[:0x8000]!=base[:0x8000] or before[0x40000:0x7e800]!=base[0x40000:0x7e800] or
            before[0x7f800:]!=base[0x7f800:]): raise ValueError('Stopped image/B preservation mismatch')
    entry=struct.unpack_from('<I',before,0x40004)[0]&~1
    if not 0x08040000<=entry<0x08040000+meta[8]: raise ValueError('B entry mismatch')
    final=TMP/(name+'-flash.bin'); row['hardware_attempted']=True
    old.prior.checkpoint(row,'restore_B_intent_no_motion')
    output=hw.debug(row,[*old.zero.off_gate(),*hw.full_compare_commands(TMP/(name+'-before.bin'),expected),
        'reset halt',f'bp {entry:#x} 2 hw',*hw.write_mailbox(previous.mailbox(3,1,2)),
        'reset run','wait_halt 25000',f'rbp {entry:#x}',
        f'if {{[lindex [reg pc] 2] != {entry:#x}}} {{error "Not before B app"}}',
        *hw.off_commands(),*hw.off_report(),f'dump_image {{{final.as_posix()}}} 0x08000000 0x80000','halt','shutdown'])
    raw=final.read_bytes(); updated=old.zero.latest_meta(raw)
    if (raw[:0x7e800]!=before[:0x7e800] or raw[0x7f800:]!=before[0x7f800:] or
            updated[2:5]!=(2,0,0) or updated[5]<=meta[5] or updated[6:10]!=meta[6:10]): raise RuntimeError('B restoration failed')
    row.update(pass_=True,final_capture=str(final),final_sha256=old.zero.digest(raw),metadata=list(updated),
        outputs=hw.check_off(output,(0x08040000,)),all_app_private_unchanged=True,b_application_not_run=True,
        final_cpu_halted=True,final_outputs_off=True,motor_commands=0)


def main():
    p=argparse.ArgumentParser(description=__doc__); mode=p.add_mutually_exclusive_group()
    mode.add_argument('--stage-off',action='store_true'); mode.add_argument('--execute-powered',type=Path)
    mode.add_argument('--restore-b-drive-off',type=Path)
    p.add_argument('--drive-off-fixed',action='store_true')
    p.add_argument('--drive-on-no-alarm-fixed-05a-emergency-off-ready',action='store_true')
    a=p.parse_args()
    if (a.stage_off or a.restore_b_drive_off) and not a.drive_off_fixed: p.error('Fresh drive OFF required')
    if a.execute_powered and not a.drive_on_no_alarm_fixed_05a_emergency_off_ready: p.error('Fresh powered conditions required')
    data=image(); baseline()
    if not (a.stage_off or a.execute_powered or a.restore_b_drive_off):
        print('OFFLINE PASS: +450mA IQ-only, Id=0, 5s, 150rpm trip; no devices'); return 0
    kind='stage' if a.stage_off else 'run' if a.execute_powered else 'restore'
    name='torque450-150-'+kind+'-'+str(time.time_ns())
    row=dict(mode=kind,pass_=False,start_attempts=0,automatic_retry=False,image_sha256=SHA,elf_sha256=ELF_SHA,
        physical_power_off=a.drive_off_fixed,steps=[],commands=[],receipt_path=str(TMP/(name+'.json')))
    old.prior.checkpoint(row,'prepared')
    try:
        if a.stage_off: stage(row,name,data)
        elif a.execute_powered: execute(row,name,a.execute_powered,data)
        else: restore(row,name,a.restore_b_drive_off,data)
    except BaseException as error:
        row.update(pass_=False,failure=str(error))
        if row.get('hardware_attempted') and not row.get('final_cpu_halted'):
            try: hw.emergency_off(row,TMP/(name+'-failed.bin'))
            except Exception as cleanup: row['cleanup_error']=str(cleanup)
    old.prior.checkpoint(row,'complete' if row['pass_'] else 'aborted')
    print(('PASS: ' if row['pass_'] else 'FAIL: ')+row['receipt_path'],flush=True)
    if row.get('failure'): print(row['failure'],flush=True)
    return 0 if row['pass_'] else 1


if __name__=='__main__': raise SystemExit(main())
