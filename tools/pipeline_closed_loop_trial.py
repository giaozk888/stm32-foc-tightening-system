"""One exact candidate A trial; optional original START only after READY gates.

No programming, forced confirmation, fault clear, threshold edits or retry.
Always shut down and halt on exit. Default verifies files only, no devices.
"""
import argparse
import json
from pathlib import Path
import re
import struct
import subprocess
import sys
import time

import pipeline_closed_loop_board_test as candidate
from firmware_transfer_iap import Uart, fields
from health_confirmation_wait import wait_health_confirmation
from latest_original_fsm_stage import full_compare_commands, write_mailbox
from original_closed_loop_updated_stage import debug, check_off, off_report
from original_closed_loop_trial import emergency_off
from protected_irq_optimized_stage import open_port
from protected_closed_loop_acceptance import protected_state, timing
from original_closed_loop_updated_trial import motion_result_ok
from tighten_synthetic_swd_recovery import latest_meta
import foc_path_profile_report as schema

STAGE = candidate.OUTPUT/'protected-pipeline-stage-1792228083458375300.json'
STAGE_SHA = 'e273a6aa28ac8da8a0e9337b9a9f715c2679ae1af1f604d365bcfed963a6b719'
COMMANDS = {
    'fw':'FW STATUS', 'profile':'MOTOR TEST PROFILE', 'state':'MOTOR TEST STATUS',
    'zero':'MOTOR TEST ZERO', 'timing':'MOTOR TEST TIMING', 'adc':'ADC TIMING',
    'commit':'ADC COMMIT', 'fault':'MOTOR TEST FAULT', 'status':'STATUS',
    'encoder':'ENC DIAG', 'health':'SELFTEST STATUS', 'safe':'ANALOG SAFE STATUS',
    'filter':'MOTOR TEST FILTER', 'protection':'MOTOR TEST PROTECTION',
}


class Console(Uart):
    def __init__(self, port):
        super().__init__(port)
        self.lines = []

    def dispatch(self, line):
        if line and len(self.lines) < 20000:
            self.lines.append(line)
        if any(x in line for x in ('BOOT HEALTH:', 'FAILED', 'HardFault', 'PROTECTED MOTOR')):
            print(line, flush=True)
        super().dispatch(line)

    def query(self, text, timeout=2):
        if text not in COMMANDS.values() and text not in ('STOP', 'ANALOG SAFE'):
            raise ValueError('Read/stop only; original START uses separate bounded runner')
        self.request += 1
        request = self.request
        self.port.write(f'{request} {text}\r\n'.encode('ascii'))
        end = time.monotonic()+timeout
        while time.monotonic() < end:
            line = self.read_line(min(.02, max(0, end-time.monotonic())))
            if line is None:
                continue
            self.dispatch(line)
            if line.startswith(f'{request} '):
                if not line.startswith(f'{request} OK '):
                    raise RuntimeError(line)
                return line
        raise TimeoutError('No ACK; no command retry: '+text)


def sample(uart):
    return {key: fields(uart.query(command)) for key, command in COMMANDS.items()}


def validate_ready(row):
    def line(key):
        return 'OK '+' '.join(f'{k}={v}' for k,v in row[key].items())
    profile = fields('OK '+candidate.MARKER.decode())
    if any(row['profile'].get(k) != v for k,v in profile.items()):
        raise RuntimeError('Wrong protected pipeline/original-FSM profile')
    protected_state(line('state'), ready=True)
    timing(line('timing'))
    expected = {
        'fw':dict(CURRENT='A',CONFIRMED='A',PENDING='-',ATTEMPTS='0',ACTIVE='0'),
        'zero':dict(STATE='3',REASON='0'),
        'adc':dict(DWT='1',MISS='0',PF='0'),
        'commit':dict(RC='1',READY='1',FAIL='0',GUARD='170'),
        'fault':dict(VALID='0'), 'status':dict(MODE='IDLE',BUSY='0',FLT='0'),
        'health':dict(READY='1',MASK='0x000'), 'safe':dict(LATCHED='0'),
    }
    for key, wanted in expected.items():
        if any(row[key].get(k) != v for k,v in wanted.items()):
            raise RuntimeError('Candidate pre-START gate failed: '+key+' '+str(row[key]))
    if int(row['adc'].get('PAIRS','0')) < 1000:
        raise RuntimeError('ADC sample evidence missing')
    # BOTTOM_LATE/LATE in coarse tail diagnostics is hypothetical after the
    # pipeline move. READY is the firmware's actual-entry/wall-history gate;
    # do not erase counters or reinterpret a tail warning as actual late.


def load_stage(data):
    candidate.configure_transaction()
    path, raw = candidate.tx.load_stage(STAGE, data)
    if candidate.digest(raw) != STAGE_SHA:
        raise ValueError('Exact independent A stage capture required')
    return path, raw


def decode(row, data):
    if not row.get('ram_backup'):
        return
    flash = candidate.tx.prior.private_path(row['final_backup']).read_bytes()
    ram = candidate.tx.prior.private_path(row['ram_backup']).read_bytes()
    if row.get('snapshot_vtor') != 0x08008000 or flash[0x8000:0x8000+len(data)] != data:
        row['snapshot_not_decoded'] = 'Stopped owner is not the exact candidate A'
        row['pass_'] = False
        return
    if len(ram) != 0x20000:
        raise ValueError('Complete same-session RAM required')
    symbols = schema.symbols(candidate.ELF)
    def words(name, size):
        address, actual = symbols[name]
        offset = address-0x20000000
        if actual != size or not 0 <= offset <= len(ram)-size:
            raise ValueError('Wrong candidate SRAM layout: '+name)
        return struct.unpack_from('<'+'I'*(size//4), ram, offset)
    def word(name):
        return words(name,4)[0]
    t = words('foc_preempt_timing',140)
    probe = words('foc_pwm_write_profile',128)
    margin = struct.unpack('<i',struct.pack('<I',probe[5]))[0]
    # In the LIGHT firmware, points increments after the real 3-store commit;
    # the heavy writes/frames/geometry fields are NOT updated. Do not display
    # their zero-filled storage as measured zero or fail a light frame count.
    actual = dict(actual_commit_count=probe[0],margin_min_ticks=margin if probe[0] else None,
        margin_min_us=margin/170 if probe[0] else None,
        actual_late_count=word('foc_ccr_probe_hard_late'),
        blocked=word('foc_ccr_probe_blocked'),post_unsafe=word('foc_ccr_probe_post_unsafe'),
        detailed_latch_geometry='NOT_RETAINED_HEAVY_PROFILE_OFF')
    row['measured'] = dict(heavy_profile=False, timing=dict(frames=None,wall_max_us=t[2]/170,
        deadline_miss=t[5],preemption_attribution='DISABLED_NOT_MEASURED'),actual_ccr=actual,
        priorities=list(words('foc_probe_irq_priority',28)),
        priority_inventory_ok=word('foc_probe_priorities_ok'),
        unexpected_irq=word('foc_probe_unexpected_irq'),
        neutral_commits=word('cl_pwm_neutral_commits'))
    # Light configuration intentionally does not retain hypothetical point
    # profiles. Never fabricate them or parse a different image's layout.
    row['measured']['hypothetical'] = 'NOT_RETAINED_HEAVY_PROFILE_OFF'
    if (not t[2] or t[5] or t[2] >= 8500 or not actual['actual_commit_count'] or
            any(actual[k] for k in ('actual_late_count','blocked','post_unsafe')) or margin <= 170):
        row.update(pass_=False, timing_pass=False)
    else:
        row['timing_pass'] = True
    address,size = symbols['foc_fault_snapshot']
    if size != 204:
        raise ValueError('Wrong first fault schema')
    head = ('valid timestamp_ms domain fault_reason timeout_reason motor_mode '
            'tightening_state state_elapsed_ms').split()
    floats = ('position_deg position_target_deg position_error_deg speed_raw_rpm '
              'speed_filtered_rpm speed_command_rpm iq_ref_A iq_measured_A '
              'id_measured_A stall_elapsed_s').split()
    tail = ('contact_candidate_ms encoder_valid encoder_errors current_validator_state '
            'current_suspect_total current_confirmed_spike current_confirmed_transition '
            'current_unresolved_total current_unresolved_consecutive '
            'current_unresolved_max_consecutive foc_cycles_max foc_normal_cycles_max '
            'foc_suspect_cycles_max foc_unresolved_cycles_max foc_deadline_miss_count '
            'adc_sample_count foc_exec_count current_hold_total hold_window_count '
            'hold_window_max hold_rate_per_mille hold_window_ms evidence_present '
            'protection_flags').split()
    evidence = ('reason now_us reference_us elapsed_us limit_us last_sample_us '
                'pending_since_us pending misses').split()
    values = struct.unpack_from('<8I10f33I',ram,address-0x20000000)
    row['first_fault'] = dict(zip(head+floats+tail+['evidence_'+n for n in evidence],values))
    row['first_fault']['raw_u'] = struct.unpack_from('<H',ram,symbols['cl_fault_u'][0]-0x20000000)[0]
    row['first_fault']['raw_v'] = struct.unpack_from('<H',ram,symbols['cl_fault_v'][0]-0x20000000)[0]
    address,size = symbols['cl_safety']
    if size != 300:
        raise ValueError('Wrong ARM-confirmed FocFeedbackSafety layout')
    confirm = struct.unpack_from('<5I',ram,address-0x20000000+124)
    row['cur_confirm'] = dict(zip(('enter','clear','fault','max_cycles','max_elapsed_us'),confirm))
    if row['first_fault']['valid']:
        row['pass_'] = False


def run_trial(row, run, data, *, motion=False):
    expected, before = load_stage(data)
    port = uart = None
    try:
        port = open_port()
        uart = Console(port)
        # No hardware effect until exact staged Flash, halted bootloader and
        # all-off registers have been checked in this same debug session.
        row['hardware_attempted'] = True
        row['trial_requests'] = 1
        row['activation_submitted'] = True  # uncertain ACK is never a retry reason
        debug(row, [*candidate.tx.prior.off_gate(0),
            *full_compare_commands(candidate.PRIVATE/(run+'-before.bin'), expected),
            'reset halt', *write_mailbox(candidate.tx.mailbox(data)), 'reset run', 'shutdown'])
        wait_health_confirmation(uart,row,fields)
        first = sample(uart)
        row['samples'].append(first)
        validate_ready(first)
        started = time.monotonic()
        while time.monotonic()-started < 30:
            end = min(started+30, time.monotonic()+2)
            while time.monotonic() < end:
                uart.poll(min(.05,max(0,end-time.monotonic())))
            last = sample(uart)
            row['samples'].append(last)
            validate_ready(last)
        if int(last['adc']['PAIRS']) <= int(first['adc']['PAIRS']):
            raise RuntimeError('ADC progression absent')
        row['preflight_pass'] = True
        print('PREFLIGHT PASS: confirmed A, calibrated, 30s neutral FOC; actual commit READY=1',flush=True)
        if motion:
            port.close()
            row['original_start_runner_invocations'] = 1
            # The existing original runner has one START, a 400 ms host stop,
            # restoration of temporary recipe values and finally-safe latch.
            proc = subprocess.run([sys.executable,'-u',str(candidate.ROOT/'tools/motor_motion_smoke.py'),
                '--execute','--expected-slot','A','--target-rpm','20'],
                capture_output=True,text=True,errors='replace',timeout=25)
            output = proc.stdout+proc.stderr
            row.update(motion_output=output,motion_returncode=proc.returncode)
            print(output,flush=True)
            motion_result_ok(proc.returncode,output)
            row['original_start_stop_pass'] = True
            positions = re.findall(r'Position change: ([+-]?[\d.]+) deg', output)
            speeds = re.findall(r'IN_MOTION .*?\bCTRL=([+-]?[\d.]+)rpm', output)
            row['motion_feedback_observed'] = bool(positions and abs(float(positions[-1])) >= .2 and
                any(abs(float(v)) > 1 for v in speeds))
            if not row['motion_feedback_observed']:
                raise RuntimeError('START/STOP replied, but movement feedback insufficient for motion acceptance')
        row['pass_'] = True
    finally:
        try:
            if row.get('hardware_attempted'):
                if uart and port.is_open:
                    try:
                        row['off_ack'] = uart.query('ANALOG SAFE', .8)
                    except BaseException as error:
                        row['uart_off_error'] = str(error)
                final = candidate.PRIVATE/(run+'-final.bin')
                emergency_off(row,final)
                raw = final.read_bytes()
                row.update(final_sha256=candidate.digest(raw),final_metadata=list(latest_meta(raw)))
                ram = candidate.PRIVATE/(run+'-ram.bin')
                output = debug(row,['init',
                    'if {([mrw 0xE000EDF0] & 0x20000) == 0} {error "Not halted"}',
                    *off_report(), f'dump_image {{{ram.as_posix()}}} 0x20000000 0x20000','shutdown'])
                regs = check_off(output,(0,0x08000000,0x08008000,0x08040000))
                row.update(snapshot_vtor=regs['VTOR'],ram_backup=str(ram))
                candidate.tx.compare_final(before,raw,data,row.get('activation_submitted',False))
                row['all_app_and_private_bytes_unchanged'] = True
        finally:
            if uart:
                row['uart'] = uart.lines
            if port and port.is_open:
                port.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute-single-trial',action='store_true')
    parser.add_argument('--physical-test-ready',action='store_true')
    parser.add_argument('--allow-one-original-start',action='store_true')
    args = parser.parse_args()
    if args.allow_one_original_start and not args.execute_single_trial:
        parser.error('No motion without a fresh exact-image trial and all preflight gates')
    if args.execute_single_trial and not args.physical_test_ready:
        parser.error('Current powered-drive/wiring/fixed motor/0.5A readiness required')
    data = candidate.image()
    if not args.execute_single_trial:
        print('OFFLINE PASS: candidate files only; no devices/private access')
        return 0
    run = candidate.PREFIX+'trial-'+str(time.time_ns())
    row = dict(pass_=False,mode='trial',image_sha256=candidate.SHA,elf_sha256=candidate.ELF_SHA,
        stage=str(STAGE),steps=[],samples=[],hardware_attempted=False,trial_requests=0,
        original_start_runner_invocations=0,force_confirmation=False,flash_programming=False,
        automatic_retry=False,protection_edits=False,torque_accuracy_verified=False)
    try:
        run_trial(row,run,data,motion=args.allow_one_original_start)
    except BaseException as error:
        row.update(pass_=False,failure=str(error))
        print('TRIAL FAILED: '+str(error),flush=True)
    finally:
        try:
            decode(row,data)
        except BaseException as error:
            row.update(pass_=False,decode_failure=str(error))
        path = candidate.OUTPUT/(run+'.json')
        path.write_text(json.dumps(row,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        print('Evidence: '+str(path),flush=True)
        if row.get('measured'):
            print(json.dumps(row['measured'],indent=2),flush=True)
    return 0 if row['pass_'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
