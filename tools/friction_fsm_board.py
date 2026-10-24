"""Pinned 240rpm/500mA/20000deg A, one supervised no-load FSM test.

Default is files only. Fresh drive-OFF inactive-A programming and independent
readback; separate powered normal A/B trial and single original START.
Preserve original B, 8s rundown timeout, 12s board lease and every other protection.
"""
import argparse
import base64
import re
import sys
import json
from pathlib import Path
import struct
import time
import zlib

import intent_fsm_board_acceptance as support
from speed500_dynamic_acceptance import mailbox
from loaded_fsm_motion import RecordedBoard,check_recipe,RECIPE_NAMES
import statistics
import accel_ff_compare
import friction_compare
import detokenize_hmi_logs  # Official Pigweed Python paths, no device access.
from pw_tokenizer.detokenize import Detokenizer
from motor_motion_smoke import require_idle_ready,stop
from foc_path_profile_report import symbols

old=support.old; hw=support.hw; TMP=support.TMP
IMAGE=old.ROOT/'foc2_app_a/build/Tightening240rpmFrictionOnCandidate/foc2.bin'
ELF=IMAGE.with_suffix('.elf')
SHA='c8c7a7e9e0753e6d39aadaddcd038df3c3f943aa0f3d167397662ac615d015f8'
ELF_SHA='91a1d63509efefedb2bd89cb0281a65995aac9eaaed64c7964ae2d06c28e306d'
BASE=TMP/'accel-ff-fsm-restore-1792483119993591500-flash.bin'
BASE_SHA='413ce5248502cc11d512bf989b4816f5e09c35c7bd850697687115b57d32a358'
HOST_MAX_SECONDS=11.95
FRICTION_A=0.20  # Wrapper-selected pinned candidate; firmware limits unchanged.
ROOT_BASE=BASE
ROOT_BASE_SHA=BASE_SHA
ROOT_RESTORE=TMP/'accel-ff-fsm-restore-1792483119993591500.json'
BASE_RESTORE_RECEIPT=ROOT_RESTORE
EXPECT_META=(1112493908,3,2,0,0,772,214900,667252788,227964,627317606,0,738724016)


def configure_baseline(path):
    """Root B772 or a fully validated output-OFF FR1 restoration, never a guess."""
    global BASE,BASE_SHA,EXPECT_META,BASE_RESTORE_RECEIPT
    path=path.resolve()
    if path.parent!=TMP.resolve(): raise ValueError('Private restore receipt required')
    r=json.loads(path.read_text('utf-8'))
    capture=Path(r.get('final_capture','')).resolve()
    if (capture.parent!=TMP.resolve() or r.get('mode')!='restore' or
            any(r.get(k) is not True for k in ('pass_','all_app_private_unchanged',
                'b_application_not_run','final_cpu_halted','final_outputs_off')) or
            r.get('motor_commands')!=0): raise ValueError('Successful halted B restore required')
    raw=capture.read_bytes(); root=ROOT_BASE.read_bytes(); meta=old.zero.latest_meta(raw)
    if len(root)!=0x80000 or old.zero.digest(root)!=ROOT_BASE_SHA:
        raise ValueError('Original B772 root capture changed')
    if (len(raw)!=0x80000 or old.zero.digest(raw)!=r.get('final_sha256') or
            meta[2:5]!=(2,0,0) or meta[8:10]!=(227964,627317606) or
            raw[:0x8000]!=root[:0x8000] or raw[0x40000:0x7e800]!=root[0x40000:0x7e800] or
            raw[0x7f800:]!=root[0x7f800:] or list(meta)!=r.get('metadata')):
        raise ValueError('Preserved B/boot/private restoration mismatch')
    if path==ROOT_RESTORE.resolve():
        if capture!=ROOT_BASE.resolve() or old.zero.digest(raw)!=ROOT_BASE_SHA or meta[5]!=772:
            raise ValueError('Exact original B772 restore required')
    else:
        data=image()
        if (r.get('image_sha256')!=SHA or r.get('elf_sha256')!=ELF_SHA or meta[5]<=772 or
                meta[6:8]!=(len(data),zlib.crc32(data)) or raw[0x8000:0x8000+len(data)]!=data):
            raise ValueError('Exact FR1 restored baseline required')
    outputs=r.get('outputs',{})
    if (outputs.get('VTOR')!=0x08040000 or not outputs.get('DHCSR',0)&0x20000 or
            outputs.get('SD',0x40)&0x40 or outputs.get('BDTR',0xC000)&0xC000 or
            outputs.get('CCER',1)):
        raise ValueError('Restoration not stopped at B entry')
    BASE=capture; BASE_SHA=old.zero.digest(raw); EXPECT_META=meta; BASE_RESTORE_RECEIPT=path


def decoded_line(row,line,decoder):
    """Keep wire evidence immutable; decoded content is explicitly host-side."""
    match=re.fullmatch(r'\[PWT\].*\[B=(\d+)\] (\$[A-Za-z0-9+/=]+)',line)
    if not match: return None
    try:
        payload=base64.b64decode(match[2][1:],validate=True)
        if len(payload)!=int(match[1]) or not 4<=len(payload)<=32:
            raise ValueError('PWT payload size mismatch')
        result=decoder.detokenize(payload)
        if not result.ok(): raise ValueError(result.error_message())
        text=str(result)
        row.setdefault('tokenized_decoded',[]).append(dict(raw=line,decoded=text))
        return text
    except (ValueError,TypeError) as error:
        row.setdefault('token_decode_errors',[]).append(dict(raw=line,error=str(error)))
        return None


class TokenConsole(old.prior.JournalConsole):
    def __init__(self,port,row):
        self.decoder=Detokenizer(ELF)
        super().__init__(port,row)
    def dispatch(self,line):
        super().dispatch(line)
        text=decoded_line(self.row,line,self.decoder)
        if text is not None: self.lines.append('[HOST_DECODE] '+text)


class TokenRecordedBoard(RecordedBoard):
    def __init__(self,port,row):
        self.decoder=Detokenizer(ELF)
        super().__init__(port,row)
    def read_line(self,seconds=.02):
        line=super().read_line(seconds)
        if line is not None: decoded_line(self.record,line,self.decoder)
        return line


def ff_status(line):
    values=hw.fields(line)
    expected=dict(ON='1',KA_NA_PER_RPM_S='187500',ACCEL_MAX_RPM_S='200',
                  FF_PEAK_UA='37500',TOKENIZED='1')
    if any(values.get(k)!=v for k,v in expected.items()):
        raise RuntimeError('Exact enabled 37.5mA acceleration FF required; no START')
    return values


def friction_status(line,enabled):
    values=hw.fields(line)
    expected=dict(ON=str(int(enabled)),I_UA=str(round(FRICTION_A*1e6)),DB_MRPM='2000',FF_ON='1',
                  KA_NA_PER_RPM_S='187500',TOKENIZED='1')
    if any(values.get(k)!=v for k,v in expected.items()):
        raise RuntimeError('Exact pinned FRIC switch/current/deadband/FF required; no START')
    return values


def image():
    data=IMAGE.read_bytes()
    commands=json.loads((IMAGE.parent/'compile_commands.json').read_text('utf-8'))
    command=next(c['command'] for c in commands if c['file'].endswith('/Core/Src/main.c'))
    support.support.require_baud(command)
    if '-DFOC_SPEED_LEGACY_AW_COMPARE' in command:
        raise ValueError('New AW must be ON, not legacy comparison')
    if (len(data)!=217420 or old.zero.digest(data)!=SHA or
            old.zero.digest(ELF.read_bytes())!=ELF_SHA or hw.image_info(data)[0]!='A' or
            any(command.count('-D'+flag+'=1')!=1 for flag in
                ('FOC_INTENT_FSM_CANDIDATE','FOC_PWM_COMMON_MODE_ENABLE','FOC_RUNDOWN240_CANDIDATE',
                 'FOC_RUNDOWN240_TRAVEL20000','FOC_ADC_COUNTS_100_40_CANDIDATE','FOC_SPEED_PI_ANTI_WINDUP','FOC_SPEED_SB3_DISABLE_CANDIDATE','FOC_SPEED_SCURVE_CANDIDATE',
                 'FOC_ACCEL_FEEDFORWARD_CANDIDATE','FOC_ACCEL_FF_ENABLED_DEFAULT',
                 'FOC_SPEED_FRICTION_CANDIDATE','FOC_FRICTION_ENABLED_DEFAULT')) or
            'firmware_common/pw_log_tokenized_override' not in command or
            'pw_log_string/public_overrides' in command):
        raise ValueError('Exact tested common-mode A BIN/ELF required')
    for marker in (b' CM=85',b'SPEED_CTRL=FR1',b'INTENT_FSM_CANDIDATE; manual START only',b'ADC_HEALTH',
                   b'METHOD=TWO_SAMPLE',b'TRIP_MA=4000',b'RPM=240 LEASE_US=12000000',
                   b'RUNDOWN240: RAM=240rpm TRIP=300rpm SAVE=OFF',b'TRAVEL=20000deg RAM only'):
        if marker not in data: raise ValueError('Candidate/protection identity missing')
    if symbols(ELF)['foc_pwm_common_mode_diag'][1]!=24:
        raise ValueError('Unexpected CM statistics ABI')
    if b'AFF R seq=' in data or b'AFF C seq=' in data:
        raise ValueError('FF log formats must not be present in flashed BIN')
    if '-DSPEED_ACCEL_FF_KA_A_PER_RPM_S=0.0001875f' not in command:
        raise ValueError('Exact reviewed Ka required')
    if any(flag not in command for flag in ('-DSPEED_FRICTION_I_A=0.20f',
            '-DSPEED_FRICTION_DEADBAND_RPM=2.0f')):
        raise ValueError('Exact reviewed friction parameters required')
    if b'FRC R seq=' in data or b'FRC C seq=' in data:
        raise ValueError('Friction log dictionary must not be in BIN')
    return data


def baseline():
    raw=BASE.read_bytes(); meta=old.zero.latest_meta(raw)
    if (len(raw)!=0x80000 or old.zero.digest(raw)!=BASE_SHA or
            meta[2:6]!=tuple(EXPECT_META[2:6]) or meta[6:10]!=tuple(EXPECT_META[6:10]) or
            zlib.crc32(raw[0x40000:0x40000+meta[8]])!=meta[9]):
        raise ValueError('Exact preserved halted B baseline baseline required')
    return raw


def stage(row,name,data):
    if row.get('physical_power_off') is not True: raise ValueError('Fresh drive OFF required')
    before=baseline(); dest=TMP/(name+'-staged.bin'); row['hardware_attempted']=True
    programming=before[0x8000:0x8000+len(data)]!=data
    program=[f'flash write_image erase {{{IMAGE.as_posix()}}} 0x08008000 bin'] if programming else []
    old.prior.checkpoint(row,'inactive_A_program_intent')
    output=hw.debug(row,[*old.zero.off_gate(),
        'if {[mrw 0xE000ED08] != 0x08040000} {error "Expected halted B baseline"}',
        *hw.full_compare_commands(TMP/(name+'-before.bin'),BASE),
        'reset halt',*hw.off_commands(),
        *program,
        f'verify_image {{{IMAGE.as_posix()}}} 0x08008000 bin',
        f'dump_image {{{dest.as_posix()}}} 0x08000000 0x80000',*hw.off_report(),'halt','shutdown'])
    raw=dest.read_bytes(); old.zero.validate_staged(raw,before,data)
    hw.debug(row,[*old.zero.off_gate(),
        *hw.full_compare_commands(TMP/(name+'-independent.bin'),dest),
        f'verify_image {{{IMAGE.as_posix()}}} 0x08008000 bin','halt','shutdown'])
    row.update(pass_=True,staged_capture=str(dest),staged_sha256=old.zero.digest(raw),
        outputs=hw.check_off(output,(0,0x08000000)),metadata=list(old.zero.latest_meta(raw)),
        independent_readback_pass=True,b_boot_private_metadata_unchanged=True,
        flash_programming=programming,activation=False,motor_commands=0,
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
    if Path(receipt.get('baseline_restore_receipt','')).resolve()!=BASE_RESTORE_RECEIPT:
        raise ValueError('Stage and selected baseline restore do not match')
    if old.zero.digest(raw)!=receipt.get('staged_sha256'): raise ValueError('Stage capture changed')
    old.zero.validate_staged(raw,baseline(),data)
    return capture,raw


def profile(line):
    values=hw.fields(line)
    expected=dict(NAME='PROTECTED_PIPELINE_CLOSED_LOOP',HARD_OFF='0',FSM='ORIGINAL',
        PIPELINE='1',LOCAL='1',RPM='240',LEASE_US='12000000',CM='85',
        SPEED_CTRL='FR1',VLIMIT_MV='1600',ILIMIT_MV='750',QUALIFIED='0')
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


def trajectory_summary(samples):
    points=[(s['elapsed_s'],float(s['status']['REF'].removesuffix('rpm')))
        for s in samples if s['status'].get('BUSY')=='1' and 'REF' in s['status']]
    if not points: return dict(observations=0)
    reached=[t for t,v in points if v>=239.9]
    return dict(observations=len(points),first_reference_rpm=points[0][1],
        first_at_target_s=reached[0] if reached else None,
        reference_max_rpm=max(v for _,v in points),
        reference_monotonic=all(b[1]>=a[1]-.11 for a,b in zip(points,points[1:])),
        qualification='sparse rounded STATUS reference, not full-rate jerk proof')


def motion(board,row):
    started=False
    try:
        require_idle_ready(board,'A')
        row['profile_before_start']=profile(board.command('MOTOR TEST PROFILE'))
        row['filter_before_start']=filter_profile(board.command('MOTOR TEST FILTER'))
        row['ff_before_start']=ff_status(board.command('MOTOR TEST FF STATUS'))
        setting='ON' if row['friction_enabled'] else 'OFF'
        row['fric_switch']=board.command('MOTOR TEST FRIC '+setting)
        row['fric_before_start']=friction_status(row['fric_switch'],row['friction_enabled'])
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
            try:
                replies=[board.command(command) for command in
                    ('MOTOR TEST FF STATUS','MOTOR TEST FF METRICS','MOTOR TEST FF METRICS2')]
                row['accel_ff_replies']=replies
                row['accel_ff_metrics']=accel_ff_compare.parse('\n'.join(replies),1)
            except Exception as error:
                row['accel_ff_metrics_error']=str(error)
        row['off_ack']=board.command('ANALOG SAFE',.8)
        safe=hw.fields(board.command('ANALOG SAFE STATUS',.8)); row['safe']=safe
        if any(safe.get(k)!=v for k,v in dict(LATCHED='1',SD='0',MOE='0',FOC='0').items()):
            raise RuntimeError('Output-OFF latch not verified')
        for command in ('MOTOR TEST FAULT','MOTOR TEST TIMING','STATUS'):
            row['postflight'][command]=board.command(command)
        if started:
            try:
                replies=[board.command(command) for command in ('MOTOR TEST FRIC STATUS',
                    'MOTOR TEST FRIC METRICS POS','MOTOR TEST FRIC METRICS2 POS',
                    'MOTOR TEST FRIC METRICS NEG','MOTOR TEST FRIC METRICS2 NEG')]
                row['friction_replies']=replies
                row['friction_metrics']=friction_compare.parse('\n'.join(replies),int(row['friction_enabled']))
            except Exception as error: row['friction_metrics_error']=str(error)
        row['speed_summary']=speed_summary(row['samples'])
        row['trajectory_summary']=trajectory_summary(row['samples'])

def decode_cm(row):
    raw=Path(row['final_capture']).read_bytes(); ram=Path(row['ram_capture']).read_bytes()
    if (old.zero.digest(raw)!=row['final_sha256'] or raw[0x8000:0x8000+len(image())]!=image() or
            row.get('outputs',{}).get('VTOR')!=0x08008000):
        raise ValueError('Same-session Flash/ELF identity missing')
    address,size=symbols(ELF)['foc_pwm_common_mode_diag']
    if size!=24: raise ValueError('CM ABI mismatch')
    row['common_mode']=dict(zip(('plans','adjusted','rejected','last_offset',
        'max_abs_offset','min_slack_ticks'),struct.unpack_from('<3Ii2I',ram,address-0x20000000)))
    address,size=symbols(ELF)['speed_accel_ff_stats']
    if size!=84: raise ValueError('Unexpected FF aggregate ABI')
    values=struct.unpack_from('<2I18f4B',ram,address-0x20000000)
    fields=('samples segment time_s max_error_rpm accel_error_integral accel_time_s '
        'decel_error_integral decel_time_s overshoot_rpm iq_peak_a integrator_peak_a '
        'iq_measured_peak_a saturation_s saturation_run_s saturation_run_max_s '
        'command_rpm direction segment_time_s settle_candidate_s settling_time_s '
        'settling settled reserved0 reserved1').split()
    row['accel_ff_ram_stats']=dict(zip(fields,values))
    address,size=symbols(ELF)['speed_friction_stats']
    if size!=120: raise ValueError('Unexpected friction aggregate ABI')
    names=('samples elapsed_s low_error_integral low_time_s cruise_error_integral cruise_time_s '
        'integrator_peak_a pi_peak_a iq_peak_a iq_measured_peak_a speed_integral '
        'wrong_direction_time_s start_delay_s').split()
    row['friction_ram_stats']={direction:dict(zip(names,struct.unpack_from('<I12f',ram,
        address-0x20000000+index*52))) for index,direction in enumerate(('POS','NEG'))}


def execute(row,name,path,data):
    if row.get('powered_no_alarm') is not True: raise ValueError('Fresh powered/no-alarm conditions required')
    staged_row=json.loads(path.read_text('utf-8'))
    if staged_row.get('friction_enabled')!=row.get('friction_enabled'):
        raise ValueError('Selected ON/OFF mode differs from staged plan')
    source,before=staged(path,data); port=support.support.open_port()
    uart=TokenConsole(port,row)
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
        board=TokenRecordedBoard('COM5',row)
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
    p.add_argument('--fric-off',action='store_true',help='One OFF baseline; no automatic ON run')
    p.add_argument('--baseline-restore',type=Path,help='Exact previously restored FR1 B receipt')
    p.add_argument('--drive-on-no-alarm-fixed-05a-emergency-off-ready',action='store_true')
    a=p.parse_args()
    if (a.stage_off or a.restore_b_drive_off) and not a.drive_off_connected_fixed: p.error('Fresh drive OFF required')
    if a.execute_powered and not a.drive_on_no_alarm_fixed_05a_emergency_off_ready: p.error('Fresh powered/no-alarm conditions required')
    data=image()
    input_path=a.execute_powered or a.restore_b_drive_off
    source=json.loads(input_path.read_text('utf-8')) if input_path else None
    selected=a.baseline_restore or (Path(source['baseline_restore_receipt']) if source else ROOT_RESTORE)
    configure_baseline(selected); baseline()
    if not (a.stage_off or a.execute_powered or a.restore_b_drive_off):
        print('OFFLINE PASS: pinned 240rpm/500mA/20000deg FR1 A and preserved B; no devices'); return 0
    kind='stage' if a.stage_off else 'run' if a.execute_powered else 'restore'
    name='friction-fsm-'+kind+'-'+str(time.time_ns())
    row=dict(mode=kind,pass_=False,start_attempts=0,automatic_retry=False,image_sha256=SHA,elf_sha256=ELF_SHA,
        steps=[],commands=[],uart=[],samples=[],postflight={},host_max_seconds=HOST_MAX_SECONDS,
        speed_anti_windup='BOUNDARY_ADMISSION',new_aw1_enabled=True,sb3_enabled=False,
        acceleration_feedforward=True,ka_a_per_rpm_s=.0001875,ff_peak_a=.0375,tokenized_logs=True,
        friction_enabled=not a.fric_off,friction_a=FRICTION_A,friction_deadband_rpm=2.0,
        baseline_restore_receipt=str(BASE_RESTORE_RECEIPT),baseline_sha256=BASE_SHA,
        trajectory='SCURVE',max_accel_rpm_s=200,max_jerk_rpm_s2=1000,
        current_jump_counts=100,current_return_counts=40,current_confirm_counts=25,current_unresolved_limit=3,
        speed_target_rpm=240,speed_iq_limit_A=.50,overspeed_trip_rpm=300,max_travel_deg=20000,
        physical_power_off=a.drive_off_connected_fixed,powered_no_alarm=a.drive_on_no_alarm_fixed_05a_emergency_off_ready,
        receipt_path=str(TMP/(name+'.json')))
    if a.restore_b_drive_off: row['friction_enabled']=source['friction_enabled']
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




