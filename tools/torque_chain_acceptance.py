"""Pinned manual +50mA/200ms torque probe. Default OFFLINE, no devices.

Separate drive-OFF staging and fresh powered execution. No original START,
negative pulse, arbitrary current, phase/zero change, SAVE, fault clear or retry.
"""
import argparse
import json
from pathlib import Path
import struct
import time
import zlib
import rundown_guard_acceptance as prior
import torque_chain_decode as decoder
from foc_path_profile_report import symbols
from firmware_transfer_iap import fields,image_info
from latest_original_fsm_stage import full_compare_commands,off_commands,write_mailbox
from original_closed_loop_updated_stage import debug,off_report,check_off
from original_closed_loop_trial import emergency_off

old=prior.old; TMP=old.TMP
IMAGE=old.ROOT/'foc2_app_a/build/TorqueChainDiagnostic/foc2.bin'
ELF=IMAGE.with_suffix('.elf')
SHA='f9c87c42f7ee52dd058901ac29fc3eac62556a5d5db109cd7bb825bd8c74a808'
ELF_SHA='3bc0a75f88e5136bb8811908c01ed3222be4191c2494e2e2f1d4aeaba1f7763f'
BASE=TMP/'rundown-guard-restore-1792328374450150600-flash.bin'
BASE_SHA='0c69211883cbc67acc1a4b28d807cc7086e3ad0891d850df6d0cbd72135b0b0c'
COMMAND='MOTOR TEST TORQUE POS ZERO CONFIRM'


def image():
    data=IMAGE.read_bytes()
    if (len(data)!=229132 or old.zero.digest(data)!=SHA or image_info(data)[0]!='A' or
        old.zero.digest(ELF.read_bytes())!=ELF_SHA): raise ValueError('Exact torque A BIN/ELF required')
    for marker in (b'IQ_MA=50 ID_MA=0 LEASE_US=200000 PERIOD_US=8000',
                   b'METHOD=TWO_SAMPLE',b'TRIP_MA=4000',b'TORQUE QUEUED'):
        if marker not in data: raise ValueError('Torque/protection identity missing')
    table=symbols(ELF)
    if table['cl_startup'][1]!=decoder.startup.TRACE_SIZE or table['torque_diag'][1]!=decoder.META.size:
        raise ValueError('Torque diagnostic ABI mismatch')
    return data


def baseline():
    raw=BASE.read_bytes(); previous=prior.baseline()
    if (len(raw)!=0x80000 or old.zero.digest(raw)!=BASE_SHA or
        old.zero.latest_meta(raw)[2:6]!=(2,0,0,669) or
        raw[0x8000:0x8000+len(prior.image())]!=prior.image() or
        raw[:0x8000]!=previous[:0x8000] or raw[0x40000:0x7e800]!=previous[0x40000:0x7e800] or
        raw[0x7f800:]!=previous[0x7f800:]): raise ValueError('Exact preserved halted B669 required')
    return raw


def stage(row,name,data):
    before=baseline(); saved=TMP/(name+'-before.bin'); row['hardware_attempted']=True
    debug(row,[*old.zero.off_gate(),
        'if {[mrw 0xE000ED08] != 0x08040000} {error "Expected halted B669"}',
        *full_compare_commands(saved,BASE),'shutdown'])
    old.prior.checkpoint(row,'baseline_verified')
    staged=TMP/(name+'-staged.bin'); row['programming_attempted']=True
    old.prior.checkpoint(row,'inactive_A_program_intent')
    output=debug(row,[*old.zero.off_gate(),*full_compare_commands(TMP/(name+'-recheck.bin'),saved),
        'reset halt',*off_commands(),
        f'flash write_image erase {{{IMAGE.as_posix()}}} 0x08008000 bin',
        f'verify_image {{{IMAGE.as_posix()}}} 0x08008000 bin',
        f'dump_image {{{staged.as_posix()}}} 0x08000000 0x80000',*off_report(),'halt','shutdown'])
    raw=staged.read_bytes(); old.zero.validate_staged(raw,before,data)
    row.update(pass_=True,staged_capture=str(staged),staged_sha256=old.zero.digest(raw),
        b_and_private_unchanged=True,activation=False,metadata=list(old.zero.latest_meta(raw)),
        outputs=check_off(output,(0,0x08000000)),final_cpu_halted=True,final_outputs_off=True)


def stage_receipt(path,data):
    r=json.loads(path.read_text('utf-8')); capture=Path(r.get('staged_capture','')).resolve()
    if (path.resolve().parent!=TMP.resolve() or capture.parent!=TMP.resolve() or
        r.get('mode')!='stage' or r.get('pass_') is not True or
        r.get('image_sha256')!=SHA or r.get('elf_sha256')!=ELF_SHA or
        not r.get('physical_power_off') or not r.get('motor_connected_fixed')):
        raise ValueError('Exact drive-OFF stage receipt required')
    raw=capture.read_bytes()
    if old.zero.digest(raw)!=r.get('staged_sha256'): raise ValueError('Stage capture changed')
    old.zero.validate_staged(raw,baseline(),data)
    return capture,raw


class TorqueConsole(old.prior.JournalConsole):
    def torque(self,command,timeout=1.0):
        # Separate narrow protocol adapter. Do NOT expand the general Console
        # read-only whitelist or expose a generic write/START/retry interface.
        if command not in (COMMAND,'MOTOR TEST TORQUE STATUS'): raise ValueError('Not a permitted torque command')
        if command==COMMAND:
            if self.row.get('pulse_attempts',0): raise RuntimeError('No second pulse or ACK retry')
            self.row['pulse_attempts']=1
            old.prior.checkpoint(self.row,'positive_pulse_intent')
        self.request+=1; request=self.request
        self.row['commands'].append(dict(command=command,at=time.monotonic()))
        self.port.write(f'{request} {command}\r\n'.encode('ascii'))
        deadline=time.monotonic()+timeout
        while time.monotonic()<deadline:
            line=self.read_line(.02)
            if line is None: continue
            self.dispatch(line)
            if line.startswith(f'{request} '):
                if not line.startswith(f'{request} OK '): raise RuntimeError(line)
                return line
        raise TimeoutError('No ACK; outcome unknown, no retry')


def preflight(uart,row):
    row['preflight_zero']=old.zero.zero_fields(uart.query('MOTOR TEST ZERO'))
    profile=fields(uart.query('MOTOR TEST PROFILE')); row['profile']=profile
    expected=dict(NAME='PROTECTED_PIPELINE_CLOSED_LOOP',HARD_OFF='0',FSM='ORIGINAL',
        PIPELINE='1',RPM='20',LEASE_US='200000',SPEED_CTRL='SB3',VLIMIT_MV='1600')
    if any(profile.get(k)!=v for k,v in expected.items()): raise RuntimeError('Wrong diagnostic profile')
    fw=fields(uart.query('FW STATUS'))
    if any(fw.get(k)!=v for k,v in dict(CURRENT='A',CONFIRMED='A',PENDING='-',ATTEMPTS='0',ACTIVE='0').items()):
        raise RuntimeError('Normal A health confirmation absent')
    s=fields(uart.torque('MOTOR TEST TORQUE STATUS')); row['torque_preflight']=s
    if any(s.get(k)!=v for k,v in dict(IQ_MA='50',ID_MA='0',LEASE_US='200000',PERIOD_US='8000',
                                      USED='0',ACTIVE='0',DENIED='0').items()):
        raise RuntimeError('Torque diagnostic unused/ready check failed')
    old.prior.wait_timing(uart,row)


def classify(row,ram):
    meta=decoder.metadata(ELF,ram,0x20000000,'arm-none-eabi-nm')
    trace=decoder.startup.extract(ELF,ram,0x20000000,'arm-none-eabi-nm')
    report=decoder.analyze(trace,meta['sign'],meta['offset_electrical_deg'])
    report['metadata']=meta; report['capture_identity_verified']=True
    row['torque_diagnostic']=report
    timing=row['snapshot']['timing']; fault=row['snapshot']['first_fault']
    row['timing_pass']=bool(0<timing['wall_max_us']<50 and not timing['deadline_miss'] and
        not timing['actual_late_count'] and timing['actual_margin_min_us']>1)
    row['pulse_execution_pass']=bool(row.get('pulse_attempts')==1 and meta['used']==1 and
        meta['sign']==1 and meta['offset_electrical_deg']==0 and
        not any(meta[k] for k in ('queued','active','admitting','denied')) and
        report['total']>=10 and not fault['valid'] and not report['first_flags'] and
        row.get('postflight_state',{}).get('STATE')=='3')
    row['pass_']=bool(row['pulse_execution_pass'] and row['timing_pass'])
    row['torque_accuracy_verified']=False
    # Execution pass is NOT a claim of stable positive mechanical torque.


def execute(row,name,path,data):
    staged,before=stage_receipt(path,data)
    port=old.prior.open_port(); uart=TorqueConsole(port,row)
    try:
        body=struct.pack('<7I',0x584f424d,1,2,2,1,len(data),zlib.crc32(data))
        mailbox=struct.unpack('<8I',body+struct.pack('<I',zlib.crc32(body)))
        row['hardware_attempted']=True; old.prior.checkpoint(row,'trial_request_intent')
        debug(row,[*old.zero.off_gate(),*full_compare_commands(TMP/(name+'-pretrial.bin'),staged),
            'reset halt',*off_commands(),*write_mailbox(mailbox),'reset run','shutdown'])
        row['trial_requests']=1; old.prior.wait_health_confirmation(uart,row,fields)
        preflight(uart,row); old.prior.checkpoint(row,'preflight_pass')
        row['pulse_ack']=uart.torque(COMMAND)
        time.sleep(.35)  # Independent board lease is 200ms; no live motion polling.
        row['postflight_state']=fields(uart.query('MOTOR TEST STATUS'))
        row['torque_postflight']=fields(uart.torque('MOTOR TEST TORQUE STATUS'))
    finally:
        if row.get('hardware_attempted'):
            try:
                row['stop_ack']=uart.query('STOP',.6)
                row['safe_ack']=uart.query('ANALOG SAFE',.6)
            except Exception as error: row['stop_error']=str(error)
        if port.is_open: port.close()
        if row.get('hardware_attempted'): old.capture_stopped(row,name,before,elf=ELF)
    if not row.get('snapshot'): raise RuntimeError('No matching candidate A snapshot')
    classify(row,Path(row['ram_capture']).read_bytes())


def restore(row,name,path,data):
    r=json.loads(path.read_text('utf-8')); expected=Path(r.get('final_capture','')).resolve()
    if (path.resolve().parent!=TMP.resolve() or expected.parent!=TMP.resolve() or r.get('mode')!='run' or
        r.get('image_sha256')!=SHA or r.get('elf_sha256')!=ELF_SHA or
        any(r.get(k) is not True for k in ('final_cpu_halted','final_outputs_off','all_app_private_unchanged'))):
        raise ValueError('Exact stopped torque receipt required')
    before=expected.read_bytes(); original=baseline(); meta=old.zero.latest_meta(before)
    if (old.zero.digest(before)!=r.get('final_sha256') or before[0x8000:0x8000+len(data)]!=data or
        before[:0x8000]!=original[:0x8000] or before[0x40000:0x7e800]!=original[0x40000:0x7e800] or
        before[0x7f800:]!=original[0x7f800:]): raise ValueError('Stopped identity/preservation mismatch')
    entry=struct.unpack_from('<I',before,0x40004)[0]&~1
    if not 0x08040000<=entry<0x08040000+meta[8]: raise ValueError('B entry mismatch')
    body=struct.pack('<7I',0x584f424d,1,3,1,2,0,0)
    mailbox=struct.unpack('<8I',body+struct.pack('<I',zlib.crc32(body)))
    final=TMP/(name+'-flash.bin'); row['hardware_attempted']=True
    output=debug(row,[*old.zero.off_gate(),*full_compare_commands(TMP/(name+'-before.bin'),expected),
        'reset halt',f'bp {entry:#x} 2 hw',*write_mailbox(mailbox),'reset run','wait_halt 25000',f'rbp {entry:#x}',
        f'if {{[lindex [reg pc] 2] != {entry:#x}}} {{error "Not before B app"}}',
        *off_commands(),*off_report(),f'dump_image {{{final.as_posix()}}} 0x08000000 0x80000','halt','shutdown'])
    raw=final.read_bytes(); current=old.zero.latest_meta(raw)
    if (raw[:0x7e800]!=before[:0x7e800] or raw[0x7f800:]!=before[0x7f800:] or
        current[2:5]!=(2,0,0) or current[5]<=meta[5] or current[6:10]!=meta[6:10]):
        raise RuntimeError('B restore preservation failed')
    row.update(pass_=True,outputs=check_off(output,(0x08040000,)),final_capture=str(final),
        final_sha256=old.zero.digest(raw),metadata=list(current),final_cpu_halted=True,
        final_outputs_off=True,all_app_private_unchanged=True,b_application_not_run=True)


def main():
    p=argparse.ArgumentParser(description=__doc__); m=p.add_mutually_exclusive_group()
    m.add_argument('--stage-off',action='store_true'); m.add_argument('--execute-positive',type=Path)
    m.add_argument('--restore-b-drive-off',type=Path)
    p.add_argument('--drive-off-connected-fixed',action='store_true')
    p.add_argument('--drive-on-no-alarm-fixed-05a-emergency-off-ready',action='store_true')
    a=p.parse_args()
    if (a.stage_off or a.restore_b_drive_off) and not a.drive_off_connected_fixed: p.error('Fresh drive OFF required')
    if a.execute_positive and not a.drive_on_no_alarm_fixed_05a_emergency_off_ready: p.error('Fresh powered readiness required')
    data=image(); baseline()
    if not (a.stage_off or a.execute_positive or a.restore_b_drive_off):
        print('OFFLINE PASS: exact torque A and halted B669; no devices'); return 0
    mode='stage' if a.stage_off else 'run' if a.execute_positive else 'restore'
    name='torque-chain-'+mode+'-'+str(time.time_ns()); receipt=TMP/(name+'.json')
    row=dict(mode=mode,pass_=False,image_sha256=SHA,elf_sha256=ELF_SHA,pulse_attempts=0,
        automatic_retry=False,physical_power_off=a.drive_off_connected_fixed,motor_connected_fixed=True,
        board_lease_us=200000,steps=[],commands=[],receipt_path=str(receipt))
    old.prior.checkpoint(row,'prepared_no_pulse')
    try:
        if a.stage_off: stage(row,name,data)
        elif a.execute_positive: execute(row,name,a.execute_positive,data)
        else: restore(row,name,a.restore_b_drive_off,data)
    except Exception as error:
        row.update(pass_=False,failure=str(error)); old.prior.checkpoint(row,'failed')
        if row.get('hardware_attempted') and not row.get('final_cpu_halted'):
            try: emergency_off(row,TMP/(name+'-failed.bin'))
            except Exception as cleanup: row['cleanup_error']=str(cleanup)
    old.prior.checkpoint(row,'complete' if row['pass_'] else 'failed')
    print(('PASS: ' if row['pass_'] else 'FAIL: ')+str(receipt),flush=True)
    if row.get('failure'): print(row['failure'],flush=True)
    return 0 if row['pass_'] else 1


if __name__=='__main__': raise SystemExit(main())
