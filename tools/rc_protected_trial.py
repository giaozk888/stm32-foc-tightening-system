"""One pinned protected RC B trial, with no motor/bridge START command.

Default offline. Explicit powered-drive/disconnected-motor phase only.
Observe computation separately from RC actuation admission; always lock/halt
at completion. Never clear faults, force confirmation or retry a trial.
"""
import argparse
import json
from pathlib import Path
import struct
import time
import zlib

import rc_protected_board_test as stage
import rc_sampling_trial as previous
from firmware_transfer_iap import fields
from latest_original_fsm_stage import write_mailbox
from protected_closed_loop_acceptance import protected_state, timing, protection
from protected_fast_math_acceptance import validate_cost
from protected_pair_fast_acceptance import validate_late
from protected_irq_priority_fix_acceptance import validate_encoder
from protected_irq_optimized_stage import open_port

STAGE_RECEIPT = stage.OUTPUT / 'rc-protected-stage-1792123087814274200.json'
STAGED_SHA = '385c53d7120d6de95e3989034b21daa5735318e540b254c95a8b47a5c3372737'
OBSERVE_SECONDS = 30.0


class Console(previous.Console):
    READ = previous.Console.READ | frozenset(('ADC COMMIT', 'MOTOR TEST PROFILE'))

    def query(self, text, timeout=2):
        if text not in self.READ and text != 'ANALOG SAFE':
            raise ValueError('Only diagnostic queries and output shutdown; no START or FW END')
        return super().query(text, timeout)


def mailbox(image):
    if len(image) != stage.SIZE or stage.digest(image) != stage.SHA:
        raise ValueError('Exact protected RC B required')
    body = struct.pack('<7I', 0x584F424D, 1, 2, 1, 2, len(image), zlib.crc32(image))
    return struct.unpack('<8I', body + struct.pack('<I', zlib.crc32(body)))


def load_stage():
    row = json.loads(STAGE_RECEIPT.read_text('utf-8'))
    if (row.get('pass_') is not True or row.get('mode') != 'stage' or
            row.get('image_sha256') != stage.SHA or row.get('staged_sha256') != STAGED_SHA or
            row.get('activation') is not False or row.get('motor_commands') != 0 or
            row.get('trial_requests') != 0 or
            any(row.get(k) is not True for k in ('metadata_unchanged',
                'all_bytes_outside_b_pages_unchanged', 'final_outputs_off', 'final_cpu_halted'))):
        raise ValueError('Exact unactivated protected RC B stage required')
    path = Path(row['staged_backup']).resolve()
    if path.parent != stage.PRIVATE.resolve():
        raise ValueError('Unexpected private capture path')
    raw = path.read_bytes()
    if stage.digest(raw) != STAGED_SHA:
        raise ValueError('Staged capture changed')
    _, before = stage.load_before()
    stage.compare_stage(before, raw, stage.pinned_image())
    return path, raw


def trial_commands(live, baseline, image):
    gate = stage.output_gate(0)
    gate[2] = 'if {[mrw 0xE000ED08] != 0 && [mrw 0xE000ED08] != 0x08000000} {error "Not halted bootloader"}'
    return [*gate, *stage.full_compare_commands(live, baseline), 'reset halt',
            *write_mailbox(mailbox(image)), 'reset run', 'shutdown']


def snapshot(uart):
    row = previous.snapshot(uart)
    row['profile'] = fields(uart.query('MOTOR TEST PROFILE'))
    row['commit'] = fields(uart.query('ADC COMMIT'))
    return row


def validate(row):
    def line(key):
        return previous.line(row[key])
    protected_state(line('state'), ready=True)
    timing(line('timing'))
    protection(line('protection'))
    validate_cost(row)
    validate_late(row)
    validate_encoder(row)
    p, a, z = row['profile'], row['adaptive'], row['robust_zero']
    if any(p.get(k) != v for k, v in (('NAME', 'RC_PROTECTED_CANDIDATE'),
            ('HARD_OFF', '0'), ('FSM', 'ORIGINAL'), ('QUALIFIED', '0'),
            ('RPM', '20'), ('LEASE_US', '400000'))):
        raise RuntimeError('Wrong protected RC/original FSM identity')
    if any(a.get(k) != v for k, v in (('ADAPT', '1'), ('HARD_OFF', '0'), ('DELAY_PAIRS', '1'))):
        raise RuntimeError('Wrong real filtered feedback identity')
    if any(z.get(k) != v for k, v in (('FLAGS', '0'), ('MAX', 'OFF'), ('SEG_MAX', 'OFF'))):
        raise RuntimeError('Robust zero unhealthy or not inherited original policy')
    if any(row['zero'].get(k) != v for k, v in (('STATE', '3'), ('REASON', '0'), ('N', '4000'))):
        raise RuntimeError('Powered startup zero not complete')
    w, adc, b, c = row['window'], row['adc'], row['buffer'], row['commit']
    if any(w.get(k) != v for k, v in (('SENSE', '2'), ('ST', '0'), ('READY', '1'),
            ('CMD4', '4184'), ('RC_MIN', '1700'), ('LATE', '1'), ('HW_VERIFIED', '0'))):
        raise RuntimeError('RC phase/geometry mismatch')
    if (adc.get('DWT') != '1' or adc.get('MISS') != '0' or adc.get('PF') != '0' or
            int(adc.get('PAIRS', '0')) < 1000 or not 0 < int(adc.get('MAX_CYC', '0')) < 8500):
        raise RuntimeError('Dual ADC / 50 us observed IRQ budget failed')
    if b.get('STK_VALID') != '1' or int(b.get('FREE_B', '0')) < 256 or int(b.get('DONE', '0')) < 1:
        raise RuntimeError('Background statistics worker unhealthy')
    if row['fault'].get('VALID') != '0' or row['status'].get('FLT') != '0':
        raise RuntimeError('Startup/runtime fault present')
    if any(c.get(k) != v for k, v in (('RC', '1'), ('CHECK', '0'), ('FAIL', '0'),
                                      ('GUARD', '170'), ('HW_VERIFIED', '0'))):
        raise RuntimeError('Unexpected commit or wrong deadline identity without START')
    if c.get('READY') not in ('0', '1') or not c.get('BOTTOM_LATE', '').isdigit():
        raise RuntimeError('Incomplete RC admission diagnostic')
    if int(c['BOTTOM_LATE']) > 0 and c['READY'] != '0':
        raise RuntimeError('Deadline admission did not reject coarse alarm')


def compare_final(before, actual, image):
    if len(actual) != 0x80000:
        raise RuntimeError('Incomplete final capture')
    if actual[:0x7E800] != before[:0x7E800] or actual[0x7F800:] != before[0x7F800:]:
        raise RuntimeError('Trial changed non-metadata Flash')
    meta = stage.latest_meta(actual)
    if (meta[5] <= stage.META[5] or meta[6:8] != stage.META[6:8] or
            meta[8:10] != (len(image), zlib.crc32(image)) or
            meta[2:5] not in ((1, 2, 1), (2, 0, 0), (1, 0, 0))):
        raise RuntimeError('Unexpected normal trial metadata')
    return meta


def trial(row, run, image):
    path, before = load_stage()
    port = uart = None
    try:
        port = open_port()
        uart = Console(port)
        row.update(hardware_attempted=True, trial_requests=1)
        stage.debug(row, trial_commands(stage.PRIVATE / (run + '-before.bin'), path, image))
        row['activation_submitted'] = True
        print('ONE protected RC B trial; diagnostic queries only; no START', flush=True)
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            try:
                fw = fields(uart.query('FW STATUS', .6))
            except TimeoutError:
                continue
            row['fw'] = fw
            if fw.get('CURRENT') == 'A' and fw.get('PENDING') == '-':
                raise RuntimeError('Rejected/rolled back to A; no retry')
            if fw.get('CURRENT') != 'B':
                continue
            try:
                state = fields(uart.query('MOTOR TEST STATUS', .6))
            except TimeoutError:
                continue  # May overlap the normal health-confirmation reset.
            row['last_state'] = state
            if state.get('STATE') == '4':
                row['sample'] = snapshot(uart)
                raise RuntimeError('Startup fault captured; no retry')
            if (fw.get('CONFIRMED') == 'B' and fw.get('PENDING') == '-' and
                    fw.get('ATTEMPTS') == '0' and fw.get('ACTIVE') == '0'):
                row['normally_confirmed'] = True
                break
            uart.poll(.02)
        else:
            raise TimeoutError('Normal B health confirmation absent')
        first = snapshot(uart)
        row['samples'].append(first)
        row['sample'] = first
        validate(first)
        print('Boot/zero PASS; observing 30s computation and RC admission, power remains off', flush=True)
        while True:
            pause_end = time.monotonic() + 1.5
            while time.monotonic() < pause_end:
                uart.poll(.05)
            last = snapshot(uart)
            row['samples'].append(last)
            row['sample'] = last
            validate(last)
            if last['host_time'] - first['host_time'] >= OBSERVE_SECONDS:
                break
        for key, counter in (('adc', 'PAIRS'), ('timing', 'WORK'), ('timing', 'OUTER'), ('buffer', 'DONE')):
            if int(last[key][counter]) <= int(first[key][counter]):
                raise RuntimeError('Sampling/FOC/worker stopped: ' + counter)
        row.update(pass_=True, compute_50us_pass=True,
                   observed_seconds=last['host_time'] - first['host_time'],
                   observed_pairs=int(last['adc']['PAIRS']) - int(first['adc']['PAIRS']),
                   compute_max_us=int(last['timing']['MAX_US']),
                   adc_irq_max_us=int(last['adc']['MAX_CYC']) / 170.0,
                   rc_software_admission=last['commit']['READY'] == '1',
                   admission_rejects_coarse_alarm=int(last['commit']['BOTTOM_LATE']) > 0
                       and last['commit']['READY'] == '0')
        print('COMPUTE PASS; RC software admission=' + last['commit']['READY'] +
              '; motor/PWM/analog qualification NOT claimed', flush=True)
    finally:
        try:
            if row.get('hardware_attempted'):
                if uart:
                    try:
                        row['off_ack'] = uart.query('ANALOG SAFE', .8)
                    except BaseException as error:
                        row['uart_off_error'] = str(error)
                final = stage.PRIVATE / (run + '-final.bin')
                stage.emergency_off(row, final)
                actual = final.read_bytes()
                meta = stage.latest_meta(actual) if actual == before else compare_final(before, actual, image)
                row.update(all_app_and_private_bytes_unchanged=True,
                           final_metadata=list(meta), final_sha256=stage.digest(actual))
                if row.get('normally_confirmed') and meta[2:5] != (2, 0, 0):
                    raise RuntimeError('Normally confirmed B not retained')
        finally:
            if uart:
                row.update(uart=uart.lines, host_motor_commands=uart.starts, host_uart_trial_commits=uart.ends)
            if port and port.is_open:
                port.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--allow-single-trial', action='store_true')
    parser.add_argument('--drive-12v-on-motor-disconnected', action='store_true')
    args = parser.parse_args()
    image = stage.pinned_image()
    mailbox(image)
    if not args.allow_single_trial:
        print('OFFLINE PASS: pinned protected RC B trial; no private/device access')
        return 0
    if not args.drive_12v_on_motor_disconnected:
        parser.error('Powered drive with motor disconnected required')
    run = 'rc-protected-trial-' + str(time.time_ns())
    row = dict(pass_=False, mode='trial', image_sha256=stage.SHA, image_bytes=len(image),
               stage_receipt=str(STAGE_RECEIPT), steps=[], samples=[], trial_requests=0,
               automatic_retry=False, force_confirmation=False, direct_metadata_write=False,
               motor_commands=0, hardware_attempted=False, requested_observation_seconds=OBSERVE_SECONDS,
               physical_pwm_preload_deadline_verified=False, bridge_analog_settling_verified=False,
               motor_closed_loop_verified=False)
    try:
        trial(row, run, image)
    except BaseException as error:
        row.update(pass_=False, failure=str(error))
        print('FAILED: ' + str(error), flush=True)
        if row.get('hardware_attempted') and not row.get('final_cpu_halted'):
            try:
                stage.emergency_off(row)
            except BaseException as cleanup:
                row['cleanup_failure'] = str(cleanup)
    finally:
        receipt = stage.OUTPUT / (run + '.json')
        receipt.write_text(json.dumps(row, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        print('Evidence: ' + str(receipt), flush=True)
    return 0 if row['pass_'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
