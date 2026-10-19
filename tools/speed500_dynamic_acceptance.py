"""Pinned SPEED-only 20rpm/500mA candidate. Files-only by default.

OFF staging restores preserved B via normal mailbox and halts at its entry,
then reset/halt writes inactive A only. No active-slot write or no-reset loader.
Powered execution is separate and never available to the staging path.
"""
import argparse
import json
from pathlib import Path
import struct
import time
import zlib
import breakaway_current_batch as prior

old=prior.old; hw=prior.legacy; TMP=prior.TMP
IMAGE=old.ROOT/'foc2_app_a/build/Speed500mADynamicDiagnostic/foc2.bin'
ELF=IMAGE.with_suffix('.elf')
SHA='36d55fa46846a1d5f613f35e7c3fd95d115f66ee6f822bfa21c35971a9225001'
ELF_SHA='c46cfd1b88968fa4bc57938a5576d831a4581c46e7aa346743f8b5e6e3b20036'
CURRENT=TMP/'breakaway5-batch-1792388770354256100-04-flash.bin'
CURRENT_SHA='df7c649c600ea750dfa8bc5e2b2384dcd7f5eef2b36503e5113741f815547f35'
STATUS='MOTOR TEST SPEED500 STATUS'
COMMAND='MOTOR TEST SPEED500 CONFIRM'


def image():
    data=IMAGE.read_bytes()
    if (len(data)!=222028 or old.zero.digest(data)!=SHA or
            old.zero.digest(ELF.read_bytes())!=ELF_SHA or hw.image_info(data)[0]!='A'):
        raise ValueError('Exact tested SPEED500 A BIN/ELF required')
    for marker in (b'OK SPEED500 RPM=20 IQ_LIMIT_MA=500 DYNAMIC_IQ=1 LEASE_US=5000000',
                   COMMAND.encode(),b'TRIP_MA=4000',b'METHOD=TWO_SAMPLE'):
        if marker not in data: raise ValueError('Candidate/protection identity missing')
    return data


def current():
    raw=CURRENT.read_bytes(); original=prior.baseline(); meta=old.zero.latest_meta(raw)
    if (len(raw)!=0x80000 or old.zero.digest(raw)!=CURRENT_SHA or meta[2:6]!=(1,0,0,696) or
            raw[0x8000:0x8000+len(prior.image())]!=prior.image() or
            raw[:0x8000]!=original[:0x8000] or raw[0x40000:0x7e800]!=original[0x40000:0x7e800] or
            raw[0x7f800:]!=original[0x7f800:] or
            zlib.crc32(raw[0x40000:0x40000+meta[8]])!=meta[9]):
        raise ValueError('Exact halted A696 with preserved CRC-valid B required')
    return raw


def mailbox(command,requester,target,size=0,crc=0):
    body=struct.pack('<7I',0x584f424d,1,command,requester,target,size,crc)
    return struct.unpack('<8I',body+struct.pack('<I',zlib.crc32(body)))


def stage(row,name,data):
    if row.get('physical_power_off') is not True: raise ValueError('Drive OFF required')
    before=current(); meta=old.zero.latest_meta(before)
    entry=struct.unpack_from('<I',before,0x40004)[0]&~1
    if not 0x08040000<=entry<0x08040000+meta[8]: raise ValueError('B reset entry invalid')
    restored=TMP/(name+'-restored-b.bin'); row['hardware_attempted']=True
    old.prior.checkpoint(row,'normal_B_restore_intent_no_motion')
    output=hw.debug(row,[*old.zero.off_gate(),
        'if {[mrw 0xE000ED08] != 0x08008000} {error "Expected halted A696"}',
        *hw.full_compare_commands(TMP/(name+'-before.bin'),CURRENT),
        'reset halt',f'bp {entry:#x} 2 hw',*hw.write_mailbox(mailbox(3,1,2)),
        'reset run','wait_halt 25000',f'rbp {entry:#x}',
        f'if {{[lindex [reg pc] 2] != {entry:#x}}} {{error "Not before B app"}}',
        *hw.off_commands(),*hw.off_report(),
        f'dump_image {{{restored.as_posix()}}} 0x08000000 0x80000','halt','shutdown'])
    row['restore_outputs']=hw.check_off(output,(0x08040000,))
    baseline=restored.read_bytes(); updated=old.zero.latest_meta(baseline)
    if (baseline[:0x7e800]!=before[:0x7e800] or baseline[0x7f800:]!=before[0x7f800:] or
            updated[2:5]!=(2,0,0) or updated[5]<=meta[5] or updated[6:10]!=meta[6:10]):
        raise RuntimeError('Normal B restore preservation failed')
    row.update(restored_capture=str(restored),restored_sha256=old.zero.digest(baseline),
        restored_metadata=list(updated),b_application_not_run=True)
    old.prior.checkpoint(row,'B_restored_halted_before_application')
    staged=TMP/(name+'-staged.bin'); row['programming_attempted']=True
    old.prior.checkpoint(row,'inactive_A_write_intent')
    output=hw.debug(row,[*old.zero.off_gate(),
        *hw.full_compare_commands(TMP/(name+'-prewrite.bin'),restored),
        'reset halt',*hw.off_commands(),
        f'flash write_image erase {{{IMAGE.as_posix()}}} 0x08008000 bin',
        f'verify_image {{{IMAGE.as_posix()}}} 0x08008000 bin',
        f'dump_image {{{staged.as_posix()}}} 0x08000000 0x80000',
        *hw.off_report(),'halt','shutdown'])
    raw=staged.read_bytes(); old.zero.validate_staged(raw,baseline,data)
    row['outputs']=hw.check_off(output,(0,0x08000000))
    independent=TMP/(name+'-independent.bin')
    hw.debug(row,[*old.zero.off_gate(),*hw.full_compare_commands(independent,staged),
        f'verify_image {{{IMAGE.as_posix()}}} 0x08008000 bin','halt','shutdown'])
    row.update(pass_=True,staged_capture=str(staged),staged_sha256=old.zero.digest(raw),
        metadata=list(old.zero.latest_meta(raw)),b_boot_private_unchanged=True,
        activation=False,motor_commands=0,final_cpu_halted=True,final_outputs_off=True,
        independent_readback_pass=True)


def staged_input(path,data):
    row=json.loads(path.read_text('utf-8')); capture=Path(row.get('staged_capture','')).resolve()
    restored=Path(row.get('restored_capture','')).resolve()
    if (path.resolve().parent!=TMP.resolve() or capture.parent!=TMP.resolve() or
            restored.parent!=TMP.resolve() or row.get('mode')!='stage' or row.get('pass_') is not True or
            row.get('physical_power_off') is not True or row.get('image_sha256')!=SHA or
            row.get('elf_sha256')!=ELF_SHA or row.get('independent_readback_pass') is not True):
        raise ValueError('Exact successful OFF stage receipt required')
    raw=capture.read_bytes(); before=restored.read_bytes()
    if old.zero.digest(raw)!=row.get('staged_sha256') or old.zero.digest(before)!=row.get('restored_sha256'):
        raise ValueError('Stage baseline changed')
    old.zero.validate_staged(raw,before,data)
    return capture,raw


def restore(row,name,path,data):
    if row.get('physical_power_off') is not True: raise ValueError('Drive OFF required')
    receipt=json.loads(path.read_text('utf-8')); capture=Path(receipt.get('final_capture','')).resolve()
    if (path.resolve().parent!=TMP.resolve() or capture.parent!=TMP.resolve() or
            receipt.get('mode') not in ('run','verify') or receipt.get('image_sha256')!=SHA or
            receipt.get('elf_sha256')!=ELF_SHA or any(receipt.get(k) is not True for k in
            ('final_cpu_halted','final_outputs_off','all_app_private_unchanged'))):
        raise ValueError('Exact stopped candidate receipt required')
    before=capture.read_bytes(); original=prior.baseline(); meta=old.zero.latest_meta(before)
    if (old.zero.digest(before)!=receipt.get('final_sha256') or meta[2:5]!=(1,0,0) or
            before[0x8000:0x8000+len(data)]!=data or meta[6:8]!=(len(data),zlib.crc32(data)) or
            before[:0x8000]!=original[:0x8000] or before[0x40000:0x7e800]!=original[0x40000:0x7e800] or
            before[0x7f800:]!=original[0x7f800:]): raise ValueError('Stopped identity/B preservation mismatch')
    entry=struct.unpack_from('<I',before,0x40004)[0]&~1
    if not 0x08040000<=entry<0x08040000+meta[8]: raise ValueError('B reset entry invalid')
    final=TMP/(name+'-flash.bin'); row['hardware_attempted']=True
    old.prior.checkpoint(row,'normal_B_restore_intent_no_motion')
    output=hw.debug(row,[*old.zero.off_gate(),
        'if {[mrw 0xE000ED08] != 0x08008000} {error "Expected stopped SPEED500 A"}',
        *hw.full_compare_commands(TMP/(name+'-before.bin'),capture),
        'reset halt',f'bp {entry:#x} 2 hw',*hw.write_mailbox(mailbox(3,1,2)),
        'reset run','wait_halt 25000',f'rbp {entry:#x}',
        f'if {{[lindex [reg pc] 2] != {entry:#x}}} {{error "Not before B app"}}',
        *hw.off_commands(),*hw.off_report(),
        f'dump_image {{{final.as_posix()}}} 0x08000000 0x80000','halt','shutdown'])
    raw=final.read_bytes(); updated=old.zero.latest_meta(raw)
    if (raw[:0x7e800]!=before[:0x7e800] or raw[0x7f800:]!=before[0x7f800:] or
            updated[2:5]!=(2,0,0) or updated[5]<=meta[5] or updated[6:10]!=meta[6:10]):
        raise RuntimeError('B restore/app-private preservation failed')
    row.update(pass_=True,final_capture=str(final),final_sha256=old.zero.digest(raw),metadata=list(updated),
        outputs=hw.check_off(output,(0x08040000,)),final_cpu_halted=True,final_outputs_off=True,
        all_app_private_unchanged=True,b_application_not_run=True,motor_commands=0)


class SpeedConsole(old.prior.JournalConsole):
    def speed(self,command,timeout=1.0):
        if command not in (STATUS,COMMAND): raise ValueError('No arbitrary motion command')
        if command==COMMAND:
            if self.row.get('start_attempts'): raise RuntimeError('No motion retry')
            self.row['start_attempts']=1; old.prior.checkpoint(self.row,'speed_manual_intent')
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
        raise TimeoutError('Unknown SPEED command outcome; never resend')


def execute(row,name,path,data,*,motion=False):
    staged,before=staged_input(path,data)
    port=old.prior.open_port(); uart=SpeedConsole(port,row)
    try:
        row['hardware_attempted']=True; old.prior.checkpoint(row,'trial_intent')
        hw.debug(row,[*old.zero.off_gate(),*hw.full_compare_commands(TMP/(name+'-before.bin'),staged),
            'reset halt',*hw.off_commands(),*hw.write_mailbox(mailbox(2,2,1,len(data),zlib.crc32(data))),
            'reset run','shutdown'])
        old.prior.wait_health_confirmation(uart,row,hw.fields)
        row['zero']=old.zero.zero_fields(uart.query('MOTOR TEST ZERO'))
        prior.expect(hw.fields(uart.query('MOTOR TEST PROFILE')),
            dict(LEASE_US='5000000',SPEED_CTRL='SB3',VLIMIT_MV='1600'),'Dynamic profile')
        row['speed_preflight']=hw.fields(uart.speed(STATUS))
        prior.expect(row['speed_preflight'],dict(RPM='20',IQ_LIMIT_MA='500',DYNAMIC_IQ='1',
            USED='0',ACTIVE='0',DENIED='0'),'Dynamic speed identity')
        prior.expect(hw.fields(uart.query('MOTOR TEST PROTECTION')),
            dict(TRIP_MA='4000',STATE='0',REASON='0',FLAGS='0'),'Protection unchanged')
        old.prior.wait_timing(uart,row); prior.standstill(uart,'1')
        row['preflight_pass']=True
        if motion:
            row['start_ack']=uart.speed(COMMAND)
            until=time.monotonic()+5.3
            while time.monotonic()<until: uart.poll(min(.05,until-time.monotonic()))
            row['post_state']=prior.off_state(uart,'3')
            prior.expect(hw.fields(uart.speed(STATUS)),dict(USED='1',ACTIVE='0',DENIED='0'),'Single session ended')
        else:
            row['post_state']=prior.off_state(uart,'1')
    finally:
        if row.get('hardware_attempted'):
            try:
                row['stop_ack']=uart.query('STOP',.6); row['safe_ack']=uart.query('ANALOG SAFE',.6)
            except Exception as error: row['stop_error']=str(error)
        if port.is_open: port.close()
        if row.get('hardware_attempted'): old.capture_stopped(row,name,before,elf=ELF)
    snap=row.get('snapshot',{}); timing=snap.get('timing',{})
    row['pass_']=bool(row.get('preflight_pass') and not row.get('stop_error') and
        snap.get('first_fault',{}).get('valid')==0 and 0<timing.get('wall_max_us',0)<50 and
        timing.get('deadline_miss')==0 and timing.get('actual_late_count')==0 and
        timing.get('actual_margin_min_us',0)>1 and row.get('final_outputs_off') and row.get('final_cpu_halted'))
    if motion and row.get('ram_capture'):
        from rundown_startup_decode import extract,decode
        trace=decode(extract(ELF,Path(row['ram_capture']).read_bytes(),0x20000000,'arm-none-eabi-nm'),period_us=200000)
        trace['interpretation']=[s.replace('20Hz','5Hz').replace('sub-50ms','sub-200ms') for s in trace['interpretation']]
        row['speed_trace']=trace
        row['speed_tracking_qualified']=False  # Observations require analysis, not just a normal STOP.


def main():
    p=argparse.ArgumentParser(description=__doc__); mode=p.add_mutually_exclusive_group()
    mode.add_argument('--restore-b-stage-a',action='store_true')
    mode.add_argument('--restore-b-drive-off',type=Path)
    mode.add_argument('--verify-compute',type=Path); mode.add_argument('--execute-speed',type=Path)
    p.add_argument('--drive-off-fixed',action='store_true')
    p.add_argument('--drive-on-no-alarm-fixed-05a-emergency-off-ready',action='store_true')
    a=p.parse_args()
    if (a.restore_b_stage_a or a.restore_b_drive_off) and not a.drive_off_fixed: p.error('Fresh drive-OFF required')
    powered=a.verify_compute or a.execute_speed
    if powered and not a.drive_on_no_alarm_fixed_05a_emergency_off_ready: p.error('Fresh powered conditions required')
    data=image(); current()
    if not (a.restore_b_stage_a or powered or a.restore_b_drive_off):
        print('OFFLINE PASS: dynamic SPEED 20rpm, +/-500mA, 5s; no device access'); return 0
    kind='stage' if a.restore_b_stage_a else 'restore' if a.restore_b_drive_off else 'run' if a.execute_speed else 'verify'
    name='speed500-'+kind+'-'+str(time.time_ns())
    row=dict(mode=kind,pass_=False,image_sha256=SHA,elf_sha256=ELF_SHA,
        physical_power_off=a.drive_off_fixed,start_attempts=0,automatic_retry=False,
        steps=[],commands=[],receipt_path=str(TMP/(name+'.json')))
    old.prior.checkpoint(row,'prepared')
    try:
        if a.restore_b_stage_a: stage(row,name,data)
        elif a.restore_b_drive_off: restore(row,name,a.restore_b_drive_off,data)
        else: execute(row,name,powered,data,motion=bool(a.execute_speed))
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
