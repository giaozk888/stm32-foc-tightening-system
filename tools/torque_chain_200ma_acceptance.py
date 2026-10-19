"""Pinned +200mA/200ms single manual pulse. OFFLINE by default.

Separate OFF staging, fresh powered preflight and OFF B restore. No automatic
negative pulse, repeat, angle/phase change, arbitrary Iq, START or fault clear.
"""
import argparse
import json
from pathlib import Path
import struct
import time
import zlib
import torque_chain_100ma_acceptance as previous

old=previous.old; TMP=previous.TMP
decoder=previous.decoder; symbols=previous.symbols; fields=previous.fields
image_info=previous.image_info; debug=previous.debug
full_compare_commands=previous.full_compare_commands; off_commands=previous.off_commands
write_mailbox=previous.write_mailbox; off_report=previous.off_report
check_off=previous.check_off; emergency_off=previous.emergency_off
TorqueConsole=previous.TorqueConsole; COMMAND=previous.COMMAND
IMAGE=old.ROOT/'foc2_app_a/build/TorqueChain200mADirectLimitDiagnostic/foc2.bin'
ELF=IMAGE.with_suffix('.elf')
SHA='3d88bf73e3c8302e88698e52b594850b377671df23179c948583d62c31dafe02'
ELF_SHA='c4c250f5307fced92bf773c63598fec056f3e180f6b33c670dfe3bd3a050bc04'
BASE=TMP/'torque200-restore-1792382884374099700-flash.bin'
BASE_SHA='3136f6ee17be34da9546b5450b2212300bfbd3f0795bd94f4b96f6df4d915578'


def image():
    data=IMAGE.read_bytes()
    if (len(data)!=229004 or old.zero.digest(data)!=SHA or image_info(data)[0]!='A' or
        old.zero.digest(ELF.read_bytes())!=ELF_SHA): raise ValueError('Exact tested 200mA A BIN/ELF required')
    for marker in (b'IQ_MA=200 ID_MA=0 LEASE_US=200000 PERIOD_US=8000',
                   b'METHOD=TWO_SAMPLE',b'TRIP_MA=4000',b'TORQUE QUEUED'):
        if marker not in data: raise ValueError('200mA/protection identity missing')
    table=symbols(ELF)
    if table['cl_startup'][1]!=decoder.startup.TRACE_SIZE or table['torque_diag'][1]!=decoder.META.size:
        raise ValueError('200mA trace ABI mismatch')
    return data


def baseline():
    raw=BASE.read_bytes(); original=previous.baseline()
    if (len(raw)!=0x80000 or old.zero.digest(raw)!=BASE_SHA or
        old.zero.latest_meta(raw)[2:6]!=(2,0,0,685) or
        old.zero.digest(raw[0x8000:0x8000+229004])!='28fc98344577c10cdd01187aeb8386b30304bc08f85edefe0d1d6ac774f66774' or
        raw[:0x8000]!=original[:0x8000] or
        raw[0x40000:0x7e800]!=original[0x40000:0x7e800] or raw[0x7f800:]!=original[0x7f800:]):
        raise ValueError('Exact halted B685 / preserved original B required')
    return raw


def stage(row,name,data):
    before=baseline(); saved=TMP/(name+'-before.bin'); row['hardware_attempted']=True
    debug(row,[*old.zero.off_gate(),
        'if {[mrw 0xE000ED08] != 0x08040000} {error "Expected halted B685"}',
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
        r.get('mode')!='stage' or r.get('pass_') is not True or r.get('image_sha256')!=SHA or
        r.get('elf_sha256')!=ELF_SHA or not r.get('physical_power_off') or not r.get('motor_connected_fixed')):
        raise ValueError('Exact 200mA drive-OFF stage receipt required')
    raw=capture.read_bytes()
    if old.zero.digest(raw)!=r.get('staged_sha256'): raise ValueError('200mA stage capture changed')
    old.zero.validate_staged(raw,baseline(),data)
    return capture,raw


def preflight(uart,row):
    row['preflight_zero']=old.zero.zero_fields(uart.query('MOTOR TEST ZERO'))
    profile=fields(uart.query('MOTOR TEST PROFILE')); row['profile']=profile
    expected=dict(NAME='PROTECTED_PIPELINE_CLOSED_LOOP',HARD_OFF='0',FSM='ORIGINAL',
        PIPELINE='1',RPM='20',LEASE_US='200000',SPEED_CTRL='SB3',VLIMIT_MV='1600')
    if any(profile.get(k)!=v for k,v in expected.items()): raise RuntimeError('Wrong 200mA profile')
    fw=fields(uart.query('FW STATUS'))
    if any(fw.get(k)!=v for k,v in dict(CURRENT='A',CONFIRMED='A',PENDING='-',ATTEMPTS='0',ACTIVE='0').items()):
        raise RuntimeError('Normal A health confirmation absent')
    s=fields(uart.torque('MOTOR TEST TORQUE STATUS')); row['torque_preflight']=s
    if any(s.get(k)!=v for k,v in dict(IQ_MA='200',ID_MA='0',LEASE_US='200000',PERIOD_US='8000',
                                      USED='0',ACTIVE='0',DENIED='0').items()):
        raise RuntimeError('200mA unused/ready check failed; no pulse')
    old.prior.wait_timing(uart,row)


def classify(row,ram,expected_sign=1):
    if expected_sign!=1: raise ValueError('Explicit fixed pulse sign required')
    meta=decoder.metadata(ELF,ram,0x20000000,'arm-none-eabi-nm')
    if meta['iq_mA']!=200 or meta['sign']!=expected_sign or meta['offset_electrical_deg']!=0:
        raise ValueError('Not the recorded fixed signed 200mA command')
    trace=decoder.startup.extract(ELF,ram,0x20000000,'arm-none-eabi-nm')
    report=decoder.analyze(trace,expected_sign,0,200)
    report['metadata']=meta; report['capture_identity_verified']=True
    row['torque_diagnostic']=report
    timing=row['snapshot']['timing']; fault=row['snapshot']['first_fault']
    row['timing_pass']=bool(0<timing['wall_max_us']<50 and not timing['deadline_miss'] and
        not timing['actual_late_count'] and timing['actual_margin_min_us']>1)
    drive=report['rows']
    row['pulse_execution_pass']=bool(row.get('pulse_attempts')==1 and meta['used']==1 and
        not any(meta[k] for k in ('queued','active','admitting','denied')) and report['total']>=10 and
        not fault['valid'] and not report['first_flags'] and row.get('postflight_state',{}).get('STATE')=='3' and
        all(r['mode']==3 and r['gates']==3 and abs(r['IqRef_A']-expected_sign*.2)<1e-6 for r in drive))
    row['host_cleanup_pass']=bool(not row.get('stop_error') and row.get('final_cpu_halted') and
        row.get('final_outputs_off') and row.get('all_app_private_unchanged'))
    row['pass_']=bool(row['pulse_execution_pass'] and row['timing_pass'] and row['host_cleanup_pass'])
    row['torque_accuracy_verified']=False
    row['mechanical_direction_verified']=False # No automatic mechanical qualification from software-only trace.


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
        time.sleep(.35) # Board lease, not host polling, owns the 200ms stop.
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
    if not row.get('snapshot'): raise RuntimeError('No matching 200mA A snapshot')
    classify(row,Path(row['ram_capture']).read_bytes())


def restore(row,name,path,data):
    r=json.loads(path.read_text('utf-8')); expected=Path(r.get('final_capture','')).resolve()
    if (path.resolve().parent!=TMP.resolve() or expected.parent!=TMP.resolve() or r.get('mode')!='run' or
        r.get('image_sha256')!=SHA or r.get('elf_sha256')!=ELF_SHA or
        any(r.get(k) is not True for k in ('final_cpu_halted','final_outputs_off','all_app_private_unchanged'))):
        raise ValueError('Exact stopped 200mA receipt required')
    before=expected.read_bytes(); original=baseline(); meta=old.zero.latest_meta(before)
    if (old.zero.digest(before)!=r.get('final_sha256') or before[0x8000:0x8000+len(data)]!=data or
        before[:0x8000]!=original[:0x8000] or before[0x40000:0x7e800]!=original[0x40000:0x7e800] or
        before[0x7f800:]!=original[0x7f800:]): raise ValueError('Stopped 200mA/B preservation mismatch')
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
        raise RuntimeError('200mA B restore preservation failed')
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
        print('OFFLINE PASS: exact direct-limit 200mA A and halted B685; no devices'); return 0
    mode='stage' if a.stage_off else 'run' if a.execute_positive else 'restore'
    name='torque200-limit-'+mode+'-'+str(time.time_ns()); receipt=TMP/(name+'.json')
    row=dict(mode=mode,pass_=False,image_sha256=SHA,elf_sha256=ELF_SHA,pulse_attempts=0,
        automatic_retry=False,physical_power_off=a.drive_off_connected_fixed,motor_connected_fixed=True,
        iq_command_mA=200,board_lease_us=200000,steps=[],commands=[],receipt_path=str(receipt))
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
