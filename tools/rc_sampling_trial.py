"""One pinned, normally confirmed RC sampling A trial; bridge hard-off.

Default is offline. Explicit powered/disconnected phase only. No START, fault
clear, forced confirmation, direct metadata write, or automatic trial retry.
"""
import argparse
import json
from pathlib import Path
import struct
import time
import zlib

import rc_sampling_board_test as stage
from latest_original_fsm_stage import write_mailbox
from firmware_transfer_iap import fields
from protected_irq_optimized_stage import open_port
from protected_irq_timing_acceptance import TimingConsole
from protected_adaptive_acceptance import validate_adaptive
from protected_irq_compact_acceptance import validate_compact
from protected_irq_priority_fix_acceptance import validate_encoder
from protected_fast_math_acceptance import validate_cost
from protected_pair_fast_acceptance import validate_late
from protected_closed_loop_acceptance import protected_state, timing, protection

STAGE_RECEIPT = stage.OUTPUT / 'rc-sampling-stage-1792121561313495400.json'
STAGED_SHA = '8be627e578bf0379d001861e96cff8faca00c99bc140c84cef1b50ebb15b1472'
OBSERVE_SECONDS = 30.0


class Console(TimingConsole):
    READ = TimingConsole.READ | frozenset(('MOTOR TEST FILTER', 'MOTOR TEST ZERO ROBUST',
                                          'MOTOR TEST RAM', 'MOTOR TEST COMPACT'))

    def query(self, text, timeout=2):
        if text not in self.READ and text != 'ANALOG SAFE':
            raise ValueError('Read/off only; no motor, reset, clear or trial UART command')
        return super().query(text, timeout)


def load_stage():
    row = json.loads(STAGE_RECEIPT.read_text(encoding='utf-8'))
    if (row.get('pass_') is not True or row.get('mode') != 'stage'
            or row.get('image_sha256') != stage.SHA or row.get('activation') is not False
            or row.get('motor_commands') != 0 or row.get('trial_requests') != 0
            or row.get('staged_sha256') != STAGED_SHA
            or any(row.get(k) is not True for k in ('metadata_unchanged',
                   'all_bytes_outside_a_pages_unchanged', 'final_cpu_halted', 'final_outputs_off'))):
        raise ValueError('Exact unactivated RC A stage required')
    path = Path(row['staged_backup']).resolve()
    if path.parent != stage.PRIVATE.resolve():
        raise ValueError('Unexpected private capture directory')
    raw = path.read_bytes()
    if stage.digest(raw) != STAGED_SHA:
        raise ValueError('Staged capture changed')
    _, before = stage.load_before()
    stage.compare_stage(before, raw, stage.pinned_image())
    return path, raw


def mailbox(image):
    if len(image) != stage.SIZE or stage.digest(image) != stage.SHA:
        raise ValueError('Exact RC hard-off A only')
    body = struct.pack('<7I', 0x584F424D, 1, 2, 2, 1, len(image), zlib.crc32(image))
    return struct.unpack('<8I', body + struct.pack('<I', zlib.crc32(body)))


def trial_commands(live, baseline, image):
    gate = stage.output_gate(0)
    gate[2] = 'if {[mrw 0xE000ED08] != 0 && [mrw 0xE000ED08] != 0x08000000} {error "Not halted bootloader"}'
    return [*gate, *stage.full_compare_commands(live, baseline), 'reset halt',
            *write_mailbox(mailbox(image)), 'reset run', 'shutdown']


def snapshot(uart):
    row = dict(host_time=time.monotonic())
    for key, command in (('state', 'MOTOR TEST STATUS'), ('zero', 'MOTOR TEST ZERO'),
            ('adaptive', 'MOTOR TEST FILTER'), ('robust_zero', 'MOTOR TEST ZERO ROBUST'),
            ('window', 'ADC WINDOW'), ('timing', 'MOTOR TEST TIMING'), ('adc', 'ADC TIMING'),
            ('protection', 'MOTOR TEST PROTECTION'), ('fault', 'MOTOR TEST FAULT'),
            ('cost', 'MOTOR TEST COST'), ('late_frame', 'MOTOR TEST LATE'),
            ('buffer', 'ADC BUFFER'), ('ram', 'MOTOR TEST RAM'),
            ('compact', 'MOTOR TEST COMPACT'), ('status', 'STATUS')):
        row[key] = fields(uart.query(command))
    enc = uart.encoder_diag()
    row['encoder'] = enc
    row.update(encoder_dma=enc['dma'], encoder_snapshot=enc.get('snapshot'),
               encoder_irq=enc.get('irq'))
    row['host_complete_time'] = time.monotonic()
    return row


def line(row):
    return 'OK ' + ' '.join(f'{k}={v}' for k, v in row.items())


def validate_identity_and_health(row):
    protected_state(line(row['state']), ready=True)
    validate_adaptive(row, segment_limit='OFF', total_limit='OFF')
    validate_compact(row)
    validate_encoder(row)
    protection(line(row['protection']))
    w = row['window']
    if any(w.get(k) != v for k, v in (('SENSE', '2'), ('ST', '0'), ('READY', '1'),
               ('CMD4', '4184'), ('RC_MIN', '1700'), ('LATE', '1'), ('HW_VERIFIED', '0'))):
        raise RuntimeError('RC phase/window identity mismatch')
    if any(row['zero'].get(k) != v for k, v in (('STATE', '3'), ('REASON', '0'), ('N', '4000'))):
        raise RuntimeError('Powered startup zero not healthy')
    if row['fault'].get('VALID') != '0' or row['status'].get('FLT') != '0':
        raise RuntimeError('FOC startup/runtime fault; no retry')
    b, a = row['buffer'], row['adc']
    if (b.get('STK_VALID') != '1' or int(b.get('FREE_B', '0')) < 256
            or int(b.get('DONE', '0')) < 1):
        raise RuntimeError('Double-buffer worker/stack check failed')
    if (a.get('DWT') != '1' or a.get('MISS') != '0' or a.get('PF') != '0'
            or int(a.get('PAIRS', '0')) < 1000):
        raise RuntimeError('Dual ADC pairing/window check failed')


def validate_50us(row):
    timing(line(row['timing']))
    validate_cost(row)
    validate_late(row)
    if not 0 < int(row['adc'].get('MAX_CYC', '0')) < 8500:
        raise RuntimeError('ADC ISR observed maximum not below 50 us')
    # ADC.LATE means coarse remaining-to-bottom exhaustion, NOT 50 us and
    # NOT a count of physically lost samples. Record it separately below.


def compare_final(before, actual, image):
    if len(actual) != 0x80000:
        raise RuntimeError('Incomplete final capture')
    if actual[:0x7E800] != before[:0x7E800] or actual[0x7F800:] != before[0x7F800:]:
        raise RuntimeError('Trial changed application/bootloader/private bytes')
    meta = stage.latest_meta(actual)
    if (meta[5] <= stage.META[5] or meta[8:10] != stage.META[8:10]
            or meta[6:8] != (len(image), zlib.crc32(image))
            or meta[2:5] not in ((2, 1, 1), (1, 0, 0), (2, 0, 0))):
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
        print('ONE RC hard-off A trial; no START; normal health confirmation only', flush=True)
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            try:
                fw = uart.query('FW STATUS', .6)
            except TimeoutError:
                continue
            row['fw'] = fw
            f = fields(fw)
            if f.get('CURRENT') == 'B':
                raise RuntimeError('Fallback B selected; no retry')
            if f.get('CURRENT') != 'A':
                continue
            try:
                state = fields(uart.query('MOTOR TEST STATUS', .6))
            except TimeoutError:
                continue  # The normal health-confirmation reset may cross a query.
            row['last_state'] = state
            if state.get('STATE') == '4':
                row['sample'] = snapshot(uart)
                raise RuntimeError('Startup fault captured; no retry')
            if (f.get('CONFIRMED') == 'A' and f.get('PENDING') == '-'
                    and f.get('ATTEMPTS') == '0' and f.get('ACTIVE') == '0'):
                row['normally_confirmed'] = True
                break
            uart.poll(.02)
            time.sleep(.1)
        else:
            raise TimeoutError('Normal A health confirmation absent')
        first = snapshot(uart)
        row['samples'].append(first)
        row['sample'] = first
        validate_identity_and_health(first)
        validate_50us(first)
        print('Zero/RC phase PASS; observing 30 seconds of hard-off ADC/FOC compute', flush=True)
        while True:
            pause_end = time.monotonic() + 1.5
            while time.monotonic() < pause_end:
                uart.poll(.05)
            last = snapshot(uart)
            row['samples'].append(last)
            row['sample'] = last
            validate_identity_and_health(last)
            validate_50us(last)
            if last['host_time'] - first['host_time'] >= OBSERVE_SECONDS:
                break
        for key, counter in (('adc', 'PAIRS'), ('timing', 'WORK'),
                             ('timing', 'OUTER'), ('buffer', 'DONE')):
            if int(last[key][counter]) <= int(first[key][counter]):
                raise RuntimeError('Sampling/FOC/background worker stopped: ' + counter)
        row.update(compute_50us_pass=True, pass_=True,
                   observed_seconds=last['host_time'] - first['host_time'],
                   compute_max_us=int(last['timing']['MAX_US']),
                   adc_irq_max_us=int(last['adc']['MAX_CYC']) / 170.0,
                   observed_pairs=int(last['adc']['PAIRS']) - int(first['adc']['PAIRS']),
                   coarse_remaining_alarm=int(last['adc']['LATE']),
                   coarse_remaining_clear=last['adc']['LATE'] == '0',
                   physical_pwm_preload_deadline_verified=False,
                   bridge_analog_settling_verified=False, motor_closed_loop_verified=False)
        print('50us COMPUTE PASS; coarse remaining alarm=' + last['adc']['LATE'] +
              '; actual PWM/analog/motor qualification NOT claimed', flush=True)
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
                # If submission failed before any metadata change, still retain
                # final off proof, without falsely requiring a completed trial.
                if actual == before and not row.get('activation_submitted'):
                    meta = stage.latest_meta(actual)
                else:
                    meta = compare_final(before, actual, image)
                row.update(all_app_and_private_bytes_unchanged=True,
                           final_metadata=list(meta), final_sha256=stage.digest(actual))
                if row.get('normally_confirmed') and meta[2:5] != (1, 0, 0):
                    raise RuntimeError('Observed confirmed A not retained in final metadata')
        finally:
            if uart:
                row.update(uart=uart.lines, host_motor_commands=uart.starts,
                           host_uart_trial_commits=uart.ends)
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
        print('OFFLINE PASS: exact RC hard-off A; no private/device access')
        return 0
    if not args.drive_12v_on_motor_disconnected:
        parser.error('Powered drive with motor disconnected required')
    run = 'rc-sampling-trial-' + str(time.time_ns())
    row = dict(pass_=False, mode='trial', image_sha256=stage.SHA, image_bytes=len(image),
               stage_receipt=str(STAGE_RECEIPT), steps=[], samples=[], trial_requests=0,
               automatic_retry=False, force_confirmation=False, direct_metadata_write=False,
               motor_commands=0, hardware_attempted=False, requested_observation_seconds=OBSERVE_SECONDS)
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
        print('TRIAL ' + ('PASS' if row['pass_'] else 'FAIL'), flush=True)
        print('Evidence: ' + str(receipt), flush=True)
    return 0 if row['pass_'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
