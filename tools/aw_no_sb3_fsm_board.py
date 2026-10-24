"""Pinned 240rpm/500mA/20000deg A, one supervised no-load FSM test.

Default is files only. Fresh drive-OFF inactive-A programming and independent
readback; separate powered normal A/B trial and single original START.
Preserve B756, 8s rundown timeout, 12s board lease and every other protection.
"""
import argparse
import json
from pathlib import Path
import struct
import time
import zlib

import intent_fsm_board_acceptance as support
from speed500_dynamic_acceptance import mailbox
from loaded_fsm_motion import RecordedBoard,check_recipe,RECIPE_NAMES
import statistics
from motor_motion_smoke import require_idle_ready,stop
from foc_path_profile_report import symbols

old=support.old; hw=support.hw; TMP=support.TMP
IMAGE=old.ROOT/'foc2_app_a/build/Tightening240rpmAwNoSb3Candidate/foc2.bin'
ELF=IMAGE.with_suffix('.elf')
SHA='d3fa11b83686b2b31c551088fdcf2d0a9872fbfd0fb50a52190075a31ecf291a'
ELF_SHA='2fb591882b2ab668802129dd716d66c68b7349dc4d8e47bd899ac1db463bfd90'
BASE=TMP/'speed-anti-windup-fsm-restore-1792466792083378600-flash.bin'
BASE_SHA='091b56601f18c416004358f6f8e43b1938f3652ec80729d798969eafdbe5753a'
HOST_MAX_SECONDS=11.95


def image():
    data=IMAGE.read_bytes()
    commands=json.loads((IMAGE.parent/'compile_commands.json').read_text('utf-8'))
    command=next(c['command'] for c in commands if c['file'].endswith('/Core/Src/main.c'))
    support.support.require_baud(command)
    if (len(data)!=228492 or old.zero.digest(data)!=SHA or
            old.zero.digest(ELF.read_bytes())!=ELF_SHA or hw.image_info(data)[0]!='A' or
            any(command.count('-D'+flag+'=1')!=1 for flag in
                ('FOC_INTENT_FSM_CANDIDATE','FOC_PWM_COMMON_MODE_ENABLE','FOC_RUNDOWN240_CANDIDATE',
                 'FOC_RUNDOWN240_TRAVEL20000','FOC_ADC_COUNTS_100_40_CANDIDATE','FOC_SPEED_PI_ANTI_WINDUP','FOC_SPEED_SB3_DISABLE_CANDIDATE'))):
        raise ValueError('Exact tested common-mode A BIN/ELF required')
    for marker in (b' CM=85',b'SPEED_CTRL=AW0',b'INTENT_FSM_CANDIDATE; manual START only',b'ADC_HEALTH',
                   b'METHOD=TWO_SAMPLE',b'TRIP_MA=4000',b'RPM=240 LEASE_US=12000000',
                   b'RUNDOWN240: RAM=240rpm TRIP=300rpm SAVE=OFF',b'TRAVEL=20000deg RAM only'):
        if marker not in data: raise ValueError('Candidate/protection identity missing')
    if symbols(ELF)['foc_pwm_common_mode_diag'][1]!=24:
        raise ValueError('Unexpected CM statistics ABI')
    return data


def baseline():
    raw=BASE.read_bytes(); meta=old.zero.latest_meta(raw)
    if (len(raw)!=0x80000 or old.zero.digest(raw)!=BASE_SHA or
            meta[2:6]!=(2,0,0,756) or meta[6:10]!=(228940,275942172,227964,627317606) or
            zlib.crc32(raw[0x40000:0x40000+meta[8]])!=meta[9]):
        raise ValueError('Exact preserved halted B756 baseline required')
    return raw


def stage(row,name,data):
    if row.get('physical_power_off') is not True: raise ValueError('Fresh drive OFF required')
    before=baseline(); dest=TMP/(name+'-staged.bin'); row['hardware_attempted']=True
    old.prior.checkpoint(row,'inactive_A_program_intent')
    output=hw.debug(row,[*old.zero.off_gate(),
        'if {[mrw 0xE000ED08] != 0x08040000} {error "Expected halted B756"}',
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
        independent_readback_pass=True,b_boot_private_metadata_unchanged=True,
        flash_programming=True,activation=False,motor_commands=0,
        final_cpu_halted=True,final_outputs_off=True)

def staged(path,data):
    receipt=json.loads(path.read_text('utf-8'))
    capture=Path(receipt.get('staged_capture','')).resolve()
    if (path.resolve().parent!=TMP.resolve() or capture.parent!=TMP.resolve() or
            receipt.get('mode')!='stage' or receipt.get('image_sha256')!=SHA or
            receipt.get('elf_sha256')!=ELF_SHA or any(receipt.get(k) is not True for k in
            ('pass_','physical_power_off','independent_readback_pass'))):
        raise ValueError('Exact successful OFF staging receipt required')
    raw=capture.read_bytes()
    if old.zero.digest(raw)!=receipt.get('staged_sha256'): raise ValueError('Stage capture changed')
    old.zero.validate_staged(raw,baseline(),data)
    return capture,raw


def profile(line):
    values=hw.fields(line)
    expected=dict(NAME='PROTECTED_PIPELINE_CLOSED_LOOP',HARD_OFF='0',FSM='ORIGINAL',
        PIPELINE='1',LOCAL='1',RPM='240',LEASE_US='12000000',CM='85',
        SPEED_CTRL='AW0',VLIMIT_MV='1600',ILIMIT_MV='750',QUALIFIED='0')
    if any(values.get(k)!=v for k,v in expected.items()):
        raise RuntimeError('Exact 240rpm/500mA image profile required; no START')
    return values

def filter_profile(line):
    values=hw.fields(line)
    expected=dict(FAST_REJECT='1',REPAIR='0',METHOD='TWO_SAMPLE',JUMP='100',
        RETURN='40',CONFIRM='25',UNRESOLVED_LIMIT='3',HOLD='1')
    if any(values.get(k)!=v for k,v in expected.items()):
        raise RuntimeError('Exact 100/40/25/3 TWO_SAMPLE filter required; no START')
    return values


def motor_stack(board):
    # ENC STACK is a second reply of ENC DIAG, NOT a standalone command.
    # Match its request ID; do not mistake an earlier DMA/DIAG ACK for stack.
    request=board.send('ENC DIAG'); end=time.monotonic()+1.0
    while time.monotonic()<end:
        line=board.read_line(min(.02,max(0,end-time.monotonic())))
        if line is None or not line.startswith(str(request)+' '): continue
        if ' ERR ' in line: raise RuntimeError('Encoder diagnostic refused; no START')
        if ' OK ENC STACK ' in line: return hw.fields(line)
    raise TimeoutError('ENC DIAG stack reply absent; no START')


def speed_summary(samples):
    running=[s for s in samples if s['status'].get('BUSY')=='1']
    if not running: return dict(observations=0,tracking_pass=False)
    speeds=[float(s['status']['CTRL'].removesuffix('rpm')) for s in running]
    positions=[float(s['status']['POS'].removesuffix('deg')) for s in running]
    end=running[-1]['elapsed_s']
    tail=[s for s in running if s['elapsed_s']>=end-.35]
    tail_speed=[float(s['status']['CTRL'].removesuffix('rpm')) for s in tail]
    return dict(observations=len(running),observed_speed_min_rpm=min(speeds),
        observed_speed_max_rpm=max(speeds),net_observed_travel_deg=positions[-1]-positions[0],
        tail_observations=len(tail),tail_mean_rpm=statistics.mean(tail_speed),
        tracking_pass=len(tail)>=3 and all(abs(v-240)<=24 for v in tail_speed),
        qualification='provisional sparse STATUS 240+/-24rpm tail, not tightening or full-rate peak')


def motion(board,row):
    started=False
    try:
        require_idle_ready(board,'A')
        row['profile_before_start']=profile(board.command('MOTOR TEST PROFILE'))
        row['filter_before_start']=filter_profile(board.command('MOTOR TEST FILTER'))
        ready=hw.fields(board.command('MOTOR TEST STATUS'))
        if any(ready.get(k)!=v for k,v in dict(STATE='1',USED='0',ZERO='3',FAULT='0',
                FLAGS='0',SD='0',MOE='0',CCER='0').items()):
            raise RuntimeError('Unused calibrated output-OFF readiness missing')
        adc=hw.fields(board.command('ADC TIMING'))
        if any(adc.get(k)!=v for k,v in dict(MISS='0',PF='0',DWT='1').items()):
            raise RuntimeError('ADC planning/pair preflight failed; no START')
        row['adc_preflight']=adc
        stack=motor_stack(board); row['motor_stack_preflight']=stack
        if stack.get('VALID')!='1' or int(stack.get('FREE_B','0'))<256:
            raise RuntimeError('Motor-task stack evidence absent/insufficient; no START')
        recipe={key:int(hw.fields(board.command('GET '+key))[key]) for key in RECIPE_NAMES}
        check_recipe(recipe); row['effective_ram_recipe']=recipe
        if recipe['RUNDOWN_RPM']!=240 or recipe['MAX_TRAVEL_DEG']!=20000 or recipe['RUNDOWN_TIMEOUT_MS']!=8000:
            raise RuntimeError('Exact RAM 240rpm/20000deg/8s recipe required; no START')
        require_idle_ready(board,'A')
        if row.get('start_attempts'): raise RuntimeError('No second START')
        started=True; row['start_attempts']=1
        old.prior.checkpoint(row,'START_ATTEMPT')
        request=board.send('START'); start=time.monotonic(); end=start+HOST_MAX_SECONDS
        row['start_request_id']=request; old.prior.checkpoint(row,'START_SENT')
        next_status=start+.05; pending=None; sent=0; ack=False
        while time.monotonic()<end:
            now=time.monotonic()
            if pending is None and now>=next_status:
                pending=board.send('STATUS'); sent=now; next_status=now+.05
            if pending is not None and now-sent>.3:
                raise TimeoutError('Feedback absent 300ms; stop, no retry')
            line=board.read_line(min(.01,max(0,end-time.monotonic())))
            if line is None: continue
            if line.startswith(str(request)+' '):
                if not line.startswith(str(request)+' OK '): raise RuntimeError('START refused')
                ack=True; row['start_ack']=line; old.prior.checkpoint(row,'START_ACK')
                print(line,flush=True)
            elif pending is not None and line.startswith(str(pending)+' '):
                pending=None
                if ' OK STATUS ' not in line: raise RuntimeError('Invalid motion status')
                values=hw.fields(line); elapsed=time.monotonic()-start
                row['samples'].append(dict(elapsed_s=elapsed,status=values))
                old.prior.checkpoint(row,'motion_feedback'); print('T=%.3f %s'%(elapsed,line),flush=True)
                if values.get('FLT')!='0': raise RuntimeError('Protection fault; no retry')
                if values.get('CONTACT')=='1':
                    raise RuntimeError('CONTACT on confirmed no-load fixture; stop, no forced tightening')
                if elapsed>.2 and values.get('BUSY')=='0':
                    row['terminal_status']=values
                    row['fsm_terminal_seen']=True
                    break
            if not ack and time.monotonic()-start>.3:
                raise TimeoutError('Unknown START result; no retry')
        old.prior.checkpoint(row,'FSM_end_or_bounded_STOP_ATTEMPT')
        stop(board); row['host_stop_elapsed_s']=time.monotonic()-start
        if not row.get('fsm_terminal_seen'):
            raise TimeoutError('FSM did not end before existing bounded host stop; no retry')
        row['fsm_observation_complete']=True
        if not ack: raise RuntimeError('No START acknowledgement')
    finally:
        if started:
            try: stop(board)
            except Exception as error: row['stop_error']=str(error)
        row['off_ack']=board.command('ANALOG SAFE',.8)
        safe=hw.fields(board.command('ANALOG SAFE STATUS',.8)); row['safe']=safe
        if any(safe.get(k)!=v for k,v in dict(LATCHED='1',SD='0',MOE='0',FOC='0').items()):
            raise RuntimeError('Output-OFF latch not verified')
        for command in ('MOTOR TEST FAULT','MOTOR TEST TIMING','STATUS'):
            row['postflight'][command]=board.command(command)
        row['speed_summary']=speed_summary(row['samples'])

def decode_cm(row):
    raw=Path(row['final_capture']).read_bytes(); ram=Path(row['ram_capture']).read_bytes()
    if (old.zero.digest(raw)!=row['final_sha256'] or raw[0x8000:0x8000+len(image())]!=image() or
            row.get('outputs',{}).get('VTOR')!=0x08008000):
        raise ValueError('Same-session Flash/ELF identity missing')
    address,size=symbols(ELF)['foc_pwm_common_mode_diag']
    if size!=24: raise ValueError('CM ABI mismatch')
    row['common_mode']=dict(zip(('plans','adjusted','rejected','last_offset',
        'max_abs_offset','min_slack_ticks'),struct.unpack_from('<3Ii2I',ram,address-0x20000000)))


def execute(row,name,path,data):
    if row.get('powered_no_alarm') is not True: raise ValueError('Fresh powered/no-alarm conditions required')
    source,before=staged(path,data); port=support.support.open_port()
    uart=old.prior.JournalConsole(port,row)
    try:
        row['hardware_attempted']=True; old.prior.checkpoint(row,'trial_intent_no_START')
        hw.debug(row,[*old.zero.off_gate(),*hw.full_compare_commands(TMP/(name+'-before.bin'),source),
            'reset halt',*hw.off_commands(),
            *hw.write_mailbox(mailbox(2,2,1,len(data),zlib.crc32(data))),'reset run','shutdown'])
        old.prior.wait_health_confirmation(uart,row,hw.fields)
        if not any('INTENT_FSM_CANDIDATE; manual START only' in line for line in uart.lines):
            raise RuntimeError('Booted candidate marker absent; no START')
        row['zero']=old.zero.zero_fields(uart.query('MOTOR TEST ZERO'))
        row['profile']=profile(uart.query('MOTOR TEST PROFILE'))
        row['filter']=filter_profile(uart.query('MOTOR TEST FILTER'))
        old.prior.wait_timing(uart,row); row['preflight_pass']=True
        old.prior.checkpoint(row,'preflight_pass'); port.close()
        board=RecordedBoard('COM5',row)
        try: motion(board,row)
        finally: board.close()
    finally:
        if port.is_open:
            try:
                row['stop_ack']=uart.query('STOP',.6); row['safe_ack']=uart.query('ANALOG SAFE',.6)
            except Exception as error: row['stop_error']=str(error)
            port.close()
        if row.get('hardware_attempted'):
            old.capture_stopped(row,name,before,elf=ELF)
            if row.get('outputs',{}).get('VTOR')==0x08008000: decode_cm(row)


    snap=row.get('snapshot')
    if not snap or snap['timing']['deadline_miss'] or snap['timing']['actual_late_count']:
        raise RuntimeError('Postflight timing evidence absent/failed; no retry')
    terminal=row.get('terminal_status',{})
    if not row.get('fsm_observation_complete'):
        raise RuntimeError('FSM observation incomplete; no retry')
    # An unloaded fixture cannot certify contact/torque completion. Preserve
    # its exact natural failure/timeout rather than reporting false success.
    raise RuntimeError('FSM terminal '+terminal.get('OUTCOME','UNKNOWN')+
        '; no-load observation is not successful tightening; no retry')

def restorable_state(meta):
    # Normal confirmed A, or this single pending-A attempt while B remains
    # confirmed. Both use the original bootloader SET_CONFIRMED_SLOT B command;
    # never CONFIRM_CURRENT A and never resume the failed A application.
    return tuple(meta[2:5]) in ((1,0,0),(2,1,1))


def restore(row,name,path,data):
    if row.get('physical_power_off') is not True: raise ValueError('Fresh drive OFF required')
    r=json.loads(path.read_text('utf-8')); expected=Path(r.get('final_capture','')).resolve()
    if (path.resolve().parent!=TMP.resolve() or expected.parent!=TMP.resolve() or
            r.get('mode')!='run' or r.get('image_sha256')!=SHA or r.get('elf_sha256')!=ELF_SHA or
            any(r.get(k) is not True for k in ('final_cpu_halted','final_outputs_off','all_app_private_unchanged'))):
        raise ValueError('Exact stopped candidate receipt required')
    before=expected.read_bytes(); base=baseline(); meta=old.zero.latest_meta(before)
    if (old.zero.digest(before)!=r.get('final_sha256') or before[0x8000:0x8000+len(data)]!=data or
            not restorable_state(meta) or meta[6:8]!=(len(data),zlib.crc32(data)) or
            before[:0x8000]!=base[:0x8000] or before[0x40000:0x7e800]!=base[0x40000:0x7e800] or
            before[0x7f800:]!=base[0x7f800:]): raise ValueError('Stopped candidate/B preservation mismatch')
    entry=struct.unpack_from('<I',before,0x40004)[0]&~1
    if not 0x08040000<=entry<0x08040000+meta[8]: raise ValueError('Invalid B entry')
    final=TMP/(name+'-flash.bin'); row['hardware_attempted']=True
    old.prior.checkpoint(row,'restore_B_intent_no_motion')
    output=hw.debug(row,[*old.zero.off_gate(),*hw.full_compare_commands(TMP/(name+'-before.bin'),expected),
        'reset halt',f'bp {entry:#x} 2 hw',*hw.write_mailbox(mailbox(3,1,2)),
        'reset run','wait_halt 25000',f'rbp {entry:#x}',
        f'if {{[lindex [reg pc] 2] != {entry:#x}}} {{error "Not before B application"}}',
        *hw.off_commands(),*hw.off_report(),f'dump_image {{{final.as_posix()}}} 0x08000000 0x80000','halt','shutdown'])
    raw=final.read_bytes(); updated=old.zero.latest_meta(raw)
    if (raw[:0x7e800]!=before[:0x7e800] or raw[0x7f800:]!=before[0x7f800:] or
            updated[2:5]!=(2,0,0) or updated[5]<=meta[5] or updated[6:10]!=meta[6:10]):
        raise RuntimeError('B restoration failed')
    row.update(pass_=True,final_capture=str(final),final_sha256=old.zero.digest(raw),metadata=list(updated),
        outputs=hw.check_off(output,(0x08040000,)),all_app_private_unchanged=True,
        b_application_not_run=True,final_cpu_halted=True,final_outputs_off=True,motor_commands=0)


def main():
    p=argparse.ArgumentParser(description=__doc__); mode=p.add_mutually_exclusive_group()
    mode.add_argument('--stage-off',action='store_true'); mode.add_argument('--execute-powered',type=Path)
    mode.add_argument('--restore-b-drive-off',type=Path)
    p.add_argument('--drive-off-connected-fixed',action='store_true')
    p.add_argument('--drive-on-no-alarm-fixed-05a-emergency-off-ready',action='store_true')
    a=p.parse_args()
    if (a.stage_off or a.restore_b_drive_off) and not a.drive_off_connected_fixed: p.error('Fresh drive OFF required')
    if a.execute_powered and not a.drive_on_no_alarm_fixed_05a_emergency_off_ready: p.error('Fresh powered/no-alarm conditions required')
    data=image(); baseline()
    if not (a.stage_off or a.execute_powered or a.restore_b_drive_off):
        print('OFFLINE PASS: pinned 240rpm/500mA/20000deg A and B756; no devices'); return 0
    kind='stage' if a.stage_off else 'run' if a.execute_powered else 'restore'
    name='aw-no-sb3-fsm-'+kind+'-'+str(time.time_ns())
    row=dict(mode=kind,pass_=False,start_attempts=0,automatic_retry=False,image_sha256=SHA,elf_sha256=ELF_SHA,
        steps=[],commands=[],uart=[],samples=[],postflight={},host_max_seconds=HOST_MAX_SECONDS,
        speed_anti_windup='AW0',sb3_enabled=False,
        current_jump_counts=100,current_return_counts=40,current_confirm_counts=25,current_unresolved_limit=3,
        speed_target_rpm=240,speed_iq_limit_A=.50,overspeed_trip_rpm=300,max_travel_deg=20000,
        physical_power_off=a.drive_off_connected_fixed,powered_no_alarm=a.drive_on_no_alarm_fixed_05a_emergency_off_ready,
        receipt_path=str(TMP/(name+'.json')))
    old.prior.checkpoint(row,'prepared')
    try:
        if a.stage_off: stage(row,name,data)
        elif a.execute_powered: execute(row,name,a.execute_powered,data)
        else: restore(row,name,a.restore_b_drive_off,data)
    except BaseException as error:
        row.update(failure=str(error),pass_=False)
        if row.get('hardware_attempted') and not row.get('final_cpu_halted'):
            try: hw.emergency_off(row,TMP/(name+'-failed.bin'))
            except Exception as cleanup: row['cleanup_error']=str(cleanup)
    old.prior.checkpoint(row,'complete' if row['pass_'] else 'aborted')
    print(('PASS: ' if row['pass_'] else 'STOPPED/FAIL: ')+row['receipt_path'],flush=True)
    if row.get('failure'): print(row['failure'],flush=True)
    return 0 if row['pass_'] else 1


if __name__=='__main__': raise SystemExit(main())






