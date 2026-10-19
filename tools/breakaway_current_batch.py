"""Supervised, bounded five-second breakaway batch. OFFLINE plan by default.

Each grade is a distinct one-shot boot/session, not a live amplitude ramp.
The board's independent five-second lease owns STOP even if this host dies.
Never changes PI, limits, bootloader, B bytes, electrical zero, or clears faults.
Staging is separate from activation: drive-OFF/reset-halt, or an already halted
output-OFF/no-reset transaction. Neither is a motion test.
"""
import argparse
import json
import math
from pathlib import Path
import struct
import time
import zlib
import torque_chain_200ma_acceptance as legacy
import breakaway_current_report as report

old=legacy.old; TMP=legacy.TMP
fields=legacy.fields; debug=legacy.debug
IMAGE=old.ROOT/'foc2_app_a/build/BreakawayFiveSecondDiagnostic/foc2.bin'
ELF=IMAGE.with_suffix('.elf')
SHA='6f45621b2c76b1b7e66a36cb0041cd2fa58ab985d2cb7614ccf8e25756f8fd95'
ELF_SHA='7ed371dc326690658fcb462d5e458953884f85f8a6cbaea6c413b7da6f91f157'
BASE=TMP/'rundown200-restore-1792383946765238700-flash.bin'
BASE_SHA='2d4fb73b4c64c3ba03b9688d3b625f85af28262ed69f9d5a63289578814bfbb4'
FAILED_BASE=TMP/'breakaway5-stage_halted-1792387371009163900-failed.bin'
FAILED_BASE_SHA='a0605d0204685d99296bc8319985b32c7d4e9c3b9c89ad59da5e2f718d3303a9'
GRADES=(100,120,150,180,200)
STATUS='MOTOR TEST BREAKAWAY STATUS'
# Quarantined after real readback mismatch on 2026-10-19. Mock tests are not
# evidence of a reliable live no-reset flash loader; do not retry this route.
HALTED_STAGE_VALIDATED=False


def plan():
    return dict(mode='OFFLINE_PLAN',hardware_access=False,duration_seconds=5,
        steps=[dict(sign=s,iq_mA=ma,seconds=5) for s in (1,-1) for ma in GRADES],
        blocked=[dict(sign=s,iq_mA=250,reason='LIMIT_BLOCKED') for s in (1,-1)],
        off_and_standstill_between_steps=True,stop_on_first_failure=True,retries=0,
        note='One pass, not three-repeat confirmed breakaway. Fixed Iq can accelerate; overspeed protection unchanged.')


def image():
    data=IMAGE.read_bytes()
    if report.digest(data)!=SHA or report.digest(ELF.read_bytes())!=ELF_SHA:
        raise ValueError('Exact tested five-second BIN/ELF required')
    if legacy.image_info(data)[0]!='A' or b'LEASE_US=5000000' not in data:
        raise ValueError('Five-second protected A identity missing')
    table=legacy.symbols(ELF)
    if table['breakaway_motion'][1]!=report.MOTION.size: raise ValueError('Motion ABI')
    return data


def baseline():
    raw=BASE.read_bytes()
    if report.digest(raw)!=BASE_SHA or len(raw)!=0x80000 or old.zero.latest_meta(raw)[2:6]!=(2,0,0,693):
        raise ValueError('Exact preserved B693 baseline required')
    return raw


def stage(row,name,data):
    before=baseline(); row['hardware_attempted']=True
    debug(row,[*old.zero.off_gate(),
        'if {[mrw 0xE000ED08] != 0x08040000} {error "Expected halted B693"}',
        *legacy.full_compare_commands(TMP/(name+'-before.bin'),BASE),'shutdown'])
    row['programming_attempted']=True; old.prior.checkpoint(row,'inactive_A_program_intent')
    dest=TMP/(name+'-staged.bin')
    output=debug(row,[*old.zero.off_gate(),
        *legacy.full_compare_commands(TMP/(name+'-recheck.bin'),BASE),
        'reset halt',*legacy.off_commands(),
        f'flash write_image erase {{{IMAGE.as_posix()}}} 0x08008000 bin',
        f'verify_image {{{IMAGE.as_posix()}}} 0x08008000 bin',
        f'dump_image {{{dest.as_posix()}}} 0x08000000 0x80000',*legacy.off_report(),'halt','shutdown'])
    raw=dest.read_bytes(); old.zero.validate_staged(raw,before,data)
    row.update(pass_=True,staged_capture=str(dest),staged_sha256=report.digest(raw),
        outputs=legacy.check_off(output,(0,0x08000000)),activation=False,
        final_cpu_halted=True,final_outputs_off=True)


def failed_baseline():
    raw=FAILED_BASE.read_bytes(); before=baseline()
    if (len(raw)!=0x80000 or report.digest(raw)!=FAILED_BASE_SHA or
        raw[:0x8000]!=before[:0x8000] or raw[0x40000:]!=before[0x40000:]):
        raise ValueError('Exact failed inactive-A capture with intact B/boot/metadata/private required')
    return raw


def recover_stage_off(row,name,data):
    """One recovery after the separately confirmed physical drive-OFF.

    Reset/halt first, then inspect again. A reset may change a stale readback;
    do not erase again if the complete desired image already verifies. No
    reset-run, metadata mailbox, application activation or retry loop.
    """
    if row.get('physical_power_off') is not True: raise ValueError('Fresh drive-OFF confirmation required')
    before=failed_baseline(); row['hardware_attempted']=True
    output=debug(row,[*old.zero.off_gate(),
        'if {[mrw 0xE000ED08] != 0x08040000} {error "Expected halted preserved B"}',
        *legacy.full_compare_commands(TMP/(name+'-before.bin'),FAILED_BASE),
        *legacy.off_report(),'shutdown'])
    row['before_outputs']=legacy.check_off(output,(0x08040000,))
    row['reset_attempted']=True; old.prior.checkpoint(row,'drive_off_reset_halt_intent')
    reset_capture=TMP/(name+'-reset.bin')
    output=debug(row,[*old.zero.off_gate(),
        *legacy.full_compare_commands(TMP/(name+'-recheck.bin'),FAILED_BASE),
        'reset halt',*legacy.off_commands(),
        f'dump_image {{{reset_capture.as_posix()}}} 0x08000000 0x80000',
        *legacy.off_report(),'halt','shutdown'])
    row['reset_outputs']=legacy.check_off(output,(0,0x08000000))
    reset_raw=reset_capture.read_bytes()
    if (len(reset_raw)!=0x80000 or reset_raw[:0x8000]!=before[:0x8000] or
        reset_raw[0x40000:]!=before[0x40000:]): raise RuntimeError('Outside inactive A changed after reset')
    row.update(reset_capture=str(reset_capture),reset_sha256=report.digest(reset_raw))
    try:
        old.zero.validate_staged(reset_raw,before,data)
        correct=True
    except ValueError:
        correct=False
    row['image_correct_after_reset']=correct
    staged=TMP/(name+'-staged.bin')
    commands=[*old.zero.off_gate(),
        *legacy.full_compare_commands(TMP/(name+'-prewrite.bin'),reset_capture)]
    if not correct:
        row['programming_attempted']=True; old.prior.checkpoint(row,'inactive_A_recovery_program_intent')
        commands += [*legacy.off_commands(),
            f'flash write_image erase {{{IMAGE.as_posix()}}} 0x08008000 bin']
    commands += [f'verify_image {{{IMAGE.as_posix()}}} 0x08008000 bin',
        f'dump_image {{{staged.as_posix()}}} 0x08000000 0x80000',
        *legacy.off_report(),'halt','shutdown']
    output=debug(row,commands)
    raw=staged.read_bytes(); old.zero.validate_staged(raw,before,data)
    row.update(pass_=True,staged_capture=str(staged),staged_sha256=report.digest(raw),
        outputs=legacy.check_off(output,(0,0x08000000)),activation=False,application_resumed=False,
        final_cpu_halted=True,final_outputs_off=True,b_and_private_unchanged=True,
        boot_and_metadata_unchanged=True,metadata=list(old.zero.latest_meta(raw)),
        recovery_source=str(FAILED_BASE),recovery_source_sha256=FAILED_BASE_SHA)


def halted_output_gate():
    """Read-only physical GPIO/peripheral checks. No halt/reset/output writes.

    In this mode the probe must find the CPU ALREADY stopped before B starts.
    Do not reset into floating GPIO while drive power could still be present.
    Flash loader may run its SRAM algorithm, never resume the application.
    """
    return [*old.zero.off_gate(),
        'if {[mrw 0xE000ED08] != 0x08040000} {error "Expected stopped B application"}',
        'if {(([mrw 0x48000800] >> 12) & 3) != 1 || ([mrw 0x48000804] & 0x40)} {error "PC6 is not push-pull output"}',
        'if {[mrw 0x48000810] & 0x40 || [mrw 0x40012C00] & 1} {error "SD pin high or PWM timer running"}']


def stage_halted(row,name,data):
    """Inactive A ONLY; preserve driven-low PC6 across programming, NO reset.

    Distinct from --stage-off: never assert that the physical 12V supply is off.
    Full-image, GPIO and halt predicates must hold before AND after programming.
    """
    if not HALTED_STAGE_VALIDATED:
        raise RuntimeError('No-reset staging quarantined after real Flash verification failure; no programming')
    before=baseline(); row['hardware_attempted']=True
    commands=[*halted_output_gate(),
        *legacy.full_compare_commands(TMP/(name+'-before.bin'),BASE),
        *legacy.off_report(),'shutdown']
    output=debug(row,commands)
    row['before_outputs']=legacy.check_off(output,(0x08040000,))
    row['halted_output_preflight']=True; old.prior.checkpoint(row,'halted_no_reset_preflight')
    dest=TMP/(name+'-staged.bin'); row['programming_attempted']=True
    old.prior.checkpoint(row,'inactive_A_program_intent')
    output=debug(row,[*halted_output_gate(),
        *legacy.full_compare_commands(TMP/(name+'-recheck.bin'),BASE),
        f'flash write_image erase {{{IMAGE.as_posix()}}} 0x08008000 bin',
        f'verify_image {{{IMAGE.as_posix()}}} 0x08008000 bin',
        *halted_output_gate()[1:],
        f'dump_image {{{dest.as_posix()}}} 0x08000000 0x80000',
        *legacy.off_report(),'halt','shutdown'])
    raw=dest.read_bytes(); old.zero.validate_staged(raw,before,data)
    if old.zero.latest_meta(raw)!=old.zero.latest_meta(before): raise RuntimeError('Metadata changed')
    row.update(pass_=True,staged_capture=str(dest),staged_sha256=report.digest(raw),
        outputs=legacy.check_off(output,(0x08040000,)),activation=False,reset_attempted=False,
        physical_power_off=False,power_state_basis='not claimed OFF; previously reported ON',
        halted_output_postflight=True,final_cpu_halted=True,final_outputs_off=True,
        b_and_private_unchanged=True,boot_and_metadata_unchanged=True,application_resumed=False,
        metadata=list(old.zero.latest_meta(raw)))


def staged_receipt(path,data):
    r=json.loads(path.read_text('utf-8')); capture=Path(r.get('staged_capture','')).resolve()
    off_stage=r.get('mode')=='stage' and r.get('physical_power_off') is True
    halted_stage=(r.get('mode')=='stage_halted' and
        all(r.get(k) is True for k in ('halted_output_preflight','halted_output_postflight',
            'final_cpu_halted','final_outputs_off','b_and_private_unchanged','boot_and_metadata_unchanged')) and
        all(r.get(k) is False for k in ('reset_attempted','activation','application_resumed')))
    if (path.resolve().parent!=TMP.resolve() or capture.parent!=TMP.resolve() or
        not (off_stage or halted_stage) or r.get('pass_') is not True or
        r.get('image_sha256')!=SHA or r.get('elf_sha256')!=ELF_SHA):
        raise ValueError('Matching OFF or no-reset halted/output-OFF staging receipt required')
    raw=capture.read_bytes()
    if report.digest(raw)!=r.get('staged_sha256'): raise ValueError('Stage changed')
    old.zero.validate_staged(raw,baseline(),data)
    return capture,raw


class BatchConsole(old.prior.JournalConsole):
    def breakaway(self,command,timeout=1.0):
        allowed={f'MOTOR TEST BREAKAWAY {d} {ma} CONFIRM' for d in ('POS','NEG') for ma in GRADES}
        if command!=STATUS and command not in allowed: raise ValueError('Not an executable batch command')
        if command!=STATUS:
            if self.row.get('pulse_attempts'): raise RuntimeError('No second pulse or ACK retry')
            self.row['pulse_attempts']=1
            old.prior.checkpoint(self.row,'pulse_intent')
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
        raise TimeoutError('Unknown command outcome; never resend')


class VerifyConsole(BatchConsole):
    """No motion command is available to the compute-only verification path."""
    def breakaway(self,command,timeout=1.0):
        if command!=STATUS: raise ValueError('Compute verification permits BREAKAWAY STATUS only')
        return super().breakaway(command,timeout)


def expect(values,wanted,label):
    if any(values.get(k)!=v for k,v in wanted.items()): raise RuntimeError(label+': '+str(values))


def off_state(uart,state):
    v=fields(uart.query('MOTOR TEST STATUS',.6))
    expect(v,dict(STATE=state,FLAGS='0',FAULT='0',SD='0',MOE='0',CCER='0'),'Outputs/state')
    return v


def standstill(uart,state,*,clock=None):
    clock=clock or time.monotonic; start=clock(); samples=[]; quiet=[]
    while True:
        now=clock()
        if now-start>5.0: raise TimeoutError('No stable one-second window within five seconds; no next grade')
        off_state(uart,state)
        v=fields(uart.query('STATUS',.6))
        expect(v,dict(MODE='IDLE',BUSY='0',FLT='0'),'Standstill mode')
        values=[float(v[k].removesuffix(unit)) for k,unit in (('POS','deg'),('CTRL','rpm'),('DET','rpm'))]
        if not all(math.isfinite(x) for x in values): raise RuntimeError('Nonfinite standstill telemetry')
        samples.append(values)
        if max(abs(x) for x in values[1:])>1:
            quiet=[]
        else:
            quiet.append((now,values))
            # Keep a rolling window, including one sample immediately before
            # its one-second boundary. A transient coast does not abort.
            while len(quiet)>1 and quiet[1][0]<=now-1.0: quiet.pop(0)
            if (len(quiet)>=10 and now-quiet[0][0]>=1.0 and
                max(x[1][0] for x in quiet)-min(x[1][0] for x in quiet)<=.10): return samples
        uart.poll(.05)


def preflight(uart,row):
    row['zero']=old.zero.zero_fields(uart.query('MOTOR TEST ZERO'))
    row['profile']=fields(uart.query('MOTOR TEST PROFILE'))
    expect(row['profile'],
        dict(NAME='PROTECTED_PIPELINE_CLOSED_LOOP',HARD_OFF='0',FSM='ORIGINAL',PIPELINE='1',
             LEASE_US='5000000',SPEED_CTRL='SB3',VLIMIT_MV='1600'),'Five-second profile')
    row['breakaway_preflight']=fields(uart.breakaway(STATUS))
    expect(row['breakaway_preflight'],dict(IQ_MA='0',LIMIT_MA='200',ID_MA='0',
        LEASE_US='5000000',PERIOD_US='200000',USED='0',ACTIVE='0',TAG='42574135'),'Unused breakaway')
    row['protection_preflight']=fields(uart.query('MOTOR TEST PROTECTION'))
    expect(row['protection_preflight'],dict(TRIP_MA='4000',STATE='0',REASON='0',FLAGS='0'),'Protection')
    old.prior.wait_timing(uart,row)
    row['stationary_before']=standstill(uart,'1')


def continue_ok(r):
    return (r.get('capture_identity_verified') is True and r.get('five_second') is True and
        r.get('classification') in ('NO_MOTION','STICK_SLIP','MARGINAL','CONTINUOUS_ROTATION') and
        all(r.get('criteria',{}).get(k) is True for k in
            ('iq_mean','iq_mae','iq_direction','accepted_current','not_saturated')))


def verify_compute(row,name,path,data):
    staged,before=staged_receipt(path,data)
    port=old.prior.open_port(); uart=VerifyConsole(port,row)
    try:
        body=struct.pack('<7I',0x584f424d,1,2,2,1,len(data),zlib.crc32(data))
        mailbox=struct.unpack('<8I',body+struct.pack('<I',zlib.crc32(body)))
        row['hardware_attempted']=True; row['activation']=True
        old.prior.checkpoint(row,'compute_only_trial_intent')
        debug(row,[*old.zero.off_gate(),
            *legacy.full_compare_commands(TMP/(name+'-before.bin'),staged),
            'reset halt',*legacy.off_commands(),*legacy.write_mailbox(mailbox),'reset run','shutdown'])
        old.prior.wait_health_confirmation(uart,row,fields)
        preflight(uart,row)
        row['postflight_state']=off_state(uart,'1')
        expect(row['postflight_state'],dict(USED='0',QUEUED='0'),'No motion session consumed')
        row['breakaway_unused']=fields(uart.breakaway(STATUS))
        expect(row['breakaway_unused'],dict(IQ_MA='0',USED='0',ACTIVE='0'),'No torque command')
        row['preflight_pass']=True
    finally:
        if row.get('hardware_attempted'):
            try:
                row['stop_ack']=uart.query('STOP',.6); row['safe_ack']=uart.query('ANALOG SAFE',.6)
            except Exception as error: row['stop_error']=str(error)
        if port.is_open: port.close()
        if row.get('hardware_attempted'): old.capture_stopped(row,name,before,elf=ELF)
    snapshot=row.get('snapshot',{}); timing=snapshot.get('timing',{})
    if (not row.get('preflight_pass') or row.get('stop_error') or
        snapshot.get('first_fault',{}).get('valid')!=0 or
        not 0<timing.get('wall_max_us',0)<50 or timing.get('deadline_miss')!=0 or
        timing.get('actual_late_count')!=0 or timing.get('actual_margin_min_us',0)<=1 or
        not row.get('final_cpu_halted') or not row.get('final_outputs_off') or
        not row.get('all_app_private_unchanged')):
        raise RuntimeError('Compute-only startup/timing/fault/cleanup verification failed')
    row.update(pass_=True,motor_commands=0,compute_only=True)


def batch_input(path,data):
    """A successful no-motion verification is also an exact halted input.

    It has normal confirmed-A metadata, so the subsequent batch resets A
    directly rather than replaying the earlier B-to-A trial mailbox.
    """
    r=json.loads(path.read_text('utf-8'))
    if r.get('mode')!='verify': return staged_receipt(path,data)
    capture=Path(r.get('final_capture','')).resolve()
    if (path.resolve().parent!=TMP.resolve() or capture.parent!=TMP.resolve() or
        r.get('pass_') is not True or r.get('compute_only') is not True or r.get('motor_commands')!=0 or
        r.get('image_sha256')!=SHA or r.get('elf_sha256')!=ELF_SHA or
        any(r.get(k) is not True for k in ('final_cpu_halted','final_outputs_off','all_app_private_unchanged'))):
        raise ValueError('Exact successful compute-only verification required')
    raw=capture.read_bytes(); base=baseline(); meta=old.zero.latest_meta(raw)
    if (len(raw)!=0x80000 or report.digest(raw)!=r.get('final_sha256') or
        raw[0x8000:0x8000+len(data)]!=data or raw[:0x8000]!=base[:0x8000] or
        raw[0x40000:0x7e800]!=base[0x40000:0x7e800] or raw[0x7f800:]!=base[0x7f800:] or
        meta[2:5]!=(1,0,0) or meta[6:8]!=(len(data),zlib.crc32(data)) or
        meta[8:10]!=old.zero.latest_meta(base)[8:10]): raise ValueError('Verified A/B identity or metadata mismatch')
    return capture,raw


def resume_coast_input(path,data):
    """Explicit human-requested continuation of a HOST-only coast abort.
    Never resume a firmware fault, bad command, missed stop or timing failure.
    """
    r=json.loads(path.read_text('utf-8')); capture=Path(r.get('final_capture','')).resolve()
    if (path.resolve().parent!=TMP.resolve() or capture.parent!=TMP.resolve() or
        r.get('mode')!='step' or r.get('failure')!='Position still moving; no next grade' or
        r.get('image_sha256')!=SHA or r.get('elf_sha256')!=ELF_SHA or r.get('pulse_attempts')!=1 or
        r.get('stop_error') or any(r.get(k) is not True for k in
            ('final_cpu_halted','final_outputs_off','all_app_private_unchanged'))):
        raise ValueError('Only the explicit host-only coast abort may continue')
    raw=capture.read_bytes(); base=baseline(); meta=old.zero.latest_meta(raw)
    if (report.digest(raw)!=r.get('final_sha256') or raw[0x8000:0x8000+len(data)]!=data or
        raw[:0x8000]!=base[:0x8000] or raw[0x40000:0x7e800]!=base[0x40000:0x7e800] or
        raw[0x7f800:]!=base[0x7f800:] or meta[2:5]!=(1,0,0) or
        meta[6:8]!=(len(data),zlib.crc32(data)) or meta[8:10]!=old.zero.latest_meta(base)[8:10]):
        raise ValueError('Exact stopped confirmed-A capture required')
    expect(r.get('post_state',{}),dict(STATE='3',USED='1',FLAGS='0',FAULT='0',SD='0',MOE='0',CCER='0'),'Prior normal stop')
    selection=r['selection']; steps=plan()['steps']
    if selection not in steps: raise ValueError('Unknown prior grade')
    analysis=report.capture_report(ELF,Path(r['ram_capture']),capture,0x08008000)
    if analysis['sign']!=selection['sign'] or analysis['iq_mA']!=selection['iq_mA'] or not continue_ok(analysis):
        raise ValueError('Prior current/timing/feedback evidence failed; no continuation')
    return capture,raw,steps.index(selection)+1,analysis


def run_step(row,name,expected,before,data,sign,ma,first):
    port=old.prior.open_port(); uart=BatchConsole(port,row)
    try:
        row['hardware_attempted']=True; old.prior.checkpoint(row,'reset_intent')
        commands=[*old.zero.off_gate(),*legacy.full_compare_commands(TMP/(name+'-before.bin'),expected),
                  'reset halt',*legacy.off_commands()]
        if first:
            body=struct.pack('<7I',0x584f424d,1,2,2,1,len(data),zlib.crc32(data))
            commands+=legacy.write_mailbox(struct.unpack('<8I',body+struct.pack('<I',zlib.crc32(body))))
        else:
            if old.zero.latest_meta(before)[2:5]!=(1,0,0): raise RuntimeError('Not confirmed A; no reset retry')
        debug(row,[*commands,'reset run','shutdown'])
        old.prior.wait_health_confirmation(uart,row,fields)
        preflight(uart,row)
        command=f'MOTOR TEST BREAKAWAY {"POS" if sign>0 else "NEG"} {ma} CONFIRM'
        row['ack']=uart.breakaway(command)
        # Pump UART but do not query/format data during the driven window.
        until=time.monotonic()+5.25
        while time.monotonic()<until: uart.poll(min(.05,until-time.monotonic()))
        row['post_state']=off_state(uart,'3')
        expect(fields(uart.breakaway(STATUS)),dict(USED='1',ACTIVE='0',SIGN=str(sign),IQ_MA=str(ma)), 'Pulse completion')
        row['stationary_after']=standstill(uart,'3')
    finally:
        if row.get('hardware_attempted'):
            try:
                row['stop_ack']=uart.query('STOP',.6); row['safe_ack']=uart.query('ANALOG SAFE',.6)
            except Exception as e: row['stop_error']=str(e)
        if port.is_open: port.close()
        if row.get('hardware_attempted'): old.capture_stopped(row,name,before,elf=ELF)
    if row.get('stop_error') or not row.get('final_outputs_off') or not row.get('all_app_private_unchanged'):
        raise RuntimeError('Cleanup/capture failed')
    r=report.capture_report(ELF,Path(row['ram_capture']),Path(row['final_capture']),0x08008000)
    if r['sign']!=sign or r['iq_mA']!=ma: raise RuntimeError('Command/capture mismatch')
    row['report']=r; row['pass_']=continue_ok(r)
    if not row['pass_']: raise RuntimeError('Diagnostic/safety gate: '+r['classification']+' '+str(r.get('reasons')))
    return Path(row['final_capture']),Path(row['final_capture']).read_bytes(),r


def run_batch(row,name,path,data,*,resume=False):
    if resume:
        expected,before,start,prior=resume_coast_input(path,data); results=[prior]
        row.update(resume_source=str(path),first_remaining_index=start)
    else:
        expected,before=batch_input(path,data); results=[]; start=0
    initial_trial=old.zero.latest_meta(before)[2]==2
    for i,step in enumerate(plan()['steps'][start:],start=start):
        child_name=f'{name}-{i:02d}'; child=dict(mode='step',pass_=False,pulse_attempts=0,steps=[],commands=[],
            image_sha256=SHA,elf_sha256=ELF_SHA,selection=step,receipt_path=str(TMP/(child_name+'.json')))
        row.setdefault('children',[]).append(child['receipt_path']); old.prior.checkpoint(row,'next_grade_intent')
        try:
            expected,before,r=run_step(child,child_name,expected,before,data,step['sign'],step['iq_mA'],i==0 and initial_trial)
            results.append(r)
        except BaseException as e:
            child['failure']=str(e); child['pass_']=False
            raise
        finally:
            old.prior.checkpoint(child,'complete' if child.get('pass_') else 'aborted')
    row.update(pass_=True,summary=report.summarize(results),final_capture=str(expected),
               final_cpu_halted=True,final_outputs_off=True,restore_B_not_performed=True)


def main():
    p=argparse.ArgumentParser(description=__doc__); group=p.add_mutually_exclusive_group()
    group.add_argument('--stage-off',action='store_true'); group.add_argument('--execute-batch',type=Path)
    group.add_argument('--stage-halted-output-off',action='store_true')
    group.add_argument('--recover-stage-off',action='store_true')
    group.add_argument('--verify-compute',type=Path)
    group.add_argument('--resume-after-coast',type=Path)
    p.add_argument('--drive-off-fixed',action='store_true')
    p.add_argument('--onsite-12v-05a-no-alarm-fixed-emergency-off',action='store_true')
    a=p.parse_args()
    if not a.stage_off and not a.recover_stage_off and not a.stage_halted_output_off and a.execute_batch is None and a.verify_compute is None and a.resume_after_coast is None:
        print(json.dumps(plan(),indent=2)); return 0
    if (a.stage_off or a.recover_stage_off) and not a.drive_off_fixed: p.error('Drive OFF required for inactive A programming')
    if a.stage_halted_output_off and not HALTED_STAGE_VALIDATED:
        p.error('No-reset staging disabled after readback failure; use separately verified drive-OFF recovery')
    if (a.execute_batch or a.verify_compute or a.resume_after_coast) and not a.onsite_12v_05a_no_alarm_fixed_emergency_off:
        p.error('Supervised powered readiness required')
    data=image(); baseline(); mode='stage' if a.stage_off or a.recover_stage_off else 'stage_halted' if a.stage_halted_output_off else 'verify' if a.verify_compute else 'batch'
    name='breakaway5-'+('recover-stage' if a.recover_stage_off else mode)+'-'+str(time.time_ns())
    row=dict(mode=mode,pass_=False,physical_power_off=a.drive_off_fixed,image_sha256=SHA,elf_sha256=ELF_SHA,
             automatic_retry=False,steps=[],commands=[],receipt_path=str(TMP/(name+'.json')))
    old.prior.checkpoint(row,'prepared')
    try:
        if a.stage_off: stage(row,name,data)
        elif a.recover_stage_off: recover_stage_off(row,name,data)
        elif a.stage_halted_output_off: stage_halted(row,name,data)
        elif a.verify_compute: verify_compute(row,name,a.verify_compute,data)
        else: run_batch(row,name,a.resume_after_coast or a.execute_batch,data,resume=bool(a.resume_after_coast))
    except BaseException as e:
        row['failure']=str(e); row['pass_']=False
        if row.get('hardware_attempted') or row.get('children'):
            try: legacy.emergency_off(row,TMP/(name+'-failed.bin'))
            except Exception as cleanup: row['cleanup_error']=str(cleanup)
    old.prior.checkpoint(row,'complete' if row['pass_'] else 'aborted')
    print(str(row['receipt_path']),flush=True)
    return 0 if row['pass_'] else 1


if __name__=='__main__': raise SystemExit(main())
