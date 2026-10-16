"""Pinned inactive-A repair. Power OFF; no PWM, ADC capture or bridge start.

Back up complete Flash privately before official UART pw_transfer staging.
Only the original confirmed B generation 420 may request this A image.
Normal bootloader/service health confirms the trial, never a forced confirm.
One output-OFF TIM7 guard test follows; a failed test never admits switching.
"""
import argparse
import hashlib
import json
import struct
import subprocess
import time

from firmware_transfer_iap import ROOT, DEFAULT_CLIENT, image_info, stage
from switch_feedback_acceptance import Console, require_switch, ORIGINAL_A, SHA as ORIGINAL_B
from zero_async_clock_acceptance import locked_baseline
from zero_retest_deploy import CLI, SN, compare_flash, require_confirmed, require_service
from zero_span100_acceptance import ADDRESSES, require_registers, observe_trial

IMAGE = ROOT / 'foc2_app_a/build/SwitchFeedbackTimerFix20261012/foc2.bin'
SHA = 'd196d66986a3c3de6befa1ab44be9feb10493f288cc6795bae678c97d97a89f1'
OUTPUT = ROOT / 'safety_backups/switch-feedback-20261012'


def image():
    data = IMAGE.read_bytes()
    if image_info(data)[0] != 'A' or hashlib.sha256(data).hexdigest() != SHA:
        raise RuntimeError('Exact offline-tested repaired A required')
    base = 0x08008000
    reset = struct.unpack_from('<I', data, 4)[0] & ~1
    irq = struct.unpack_from('<I', data, (16 + 55) * 4)[0]
    if data[reset-base:reset-base+2] != b'\x72\xb6':
        raise RuntimeError('Reset interrupt masking missing')
    if not irq & 1 or not base <= irq & ~1 < base + len(data):
        raise RuntimeError('Independent guard vector missing')
    for marker in (b'OPEN_LOAD_ONLY', b'MOTOR_READY=0', b'IRQ_SR='):
        if marker not in data:
            raise RuntimeError('Repaired diagnostic marker missing')
    return data


def baseline(data):
    row = locked_baseline(data, known={'A': frozenset((ORIGINAL_A,)),
                                     'B': frozenset((ORIGINAL_B,))})
    if row['current'] != 'B' or row['generation'] != 420:
        raise RuntimeError('Exact confirmed output-locked B generation 420 required')
    return row


def guard_result(line):
    row = require_switch(line, mode=4)
    if (row.get('ACTIVE') != '0' or row.get('REASON') != '2' or row.get('N') != '0'
            or not 185000 <= int(row.get('US', '0')) <= 195000
            or not int(row.get('DONE', '0')) & 16 or row.get('IRQ') != '1'
            or not int(row.get('IRQ_SR', '0')) & 1):
        raise RuntimeError('Repaired independent cutoff failed; switching NOT admitted')
    return row


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--inspect', action='store_true')
    parser.add_argument('--allow-inactive-a', action='store_true')
    parser.add_argument('--drive-12v-off', action='store_true')
    args = parser.parse_args()
    if args.inspect == args.allow_inactive_a:
        parser.error('Choose inspect OR explicitly authorized inactive-A deployment')
    if args.allow_inactive_a and not args.drive_12v_off:
        parser.error('Drive 12 V OFF required')
    data = image()
    OUTPUT.mkdir(parents=True, exist_ok=True)
    private = OUTPUT / 'private'
    private.mkdir(exist_ok=True)
    subprocess.run(['icacls', str(private), '/inheritance:r', '/grant:r',
                    '*S-1-5-18:(OI)(CI)F', '*S-1-5-32-544:(OI)(CI)F'],
                   check=True, capture_output=True)
    run = str(time.time_ns())
    target = OUTPUT / f'timerfix-{run}.json'
    record = dict(pass_=False, inspect_only=args.inspect, target_slot='A',
                  image_sha256=SHA, bridge_enabled=False, pwm_enabled=False,
                  motion_commands=False, force_confirm=False, automatic_retry=False, steps=[])
    port = uart = None

    def cli(*tokens):
        if tokens[0] not in ('-u', '-r32'):
            raise ValueError('Read-only SWD only')
        p = subprocess.run([CLI, '-c', 'port=SWD', 'mode=HOTPLUG', 'freq=1000',
                            'sn='+SN, *map(str, tokens)], capture_output=True,
                           text=True, errors='replace', timeout=30)
        record['steps'].append(dict(args=list(map(str, tokens)), code=p.returncode,
                                    output=p.stdout+p.stderr))
        if p.returncode or 'Error:' in p.stdout+p.stderr:
            raise RuntimeError('SWD read failed; no retry')
        return p.stdout+p.stderr

    def capture(name):
        path = private / f'{run}-timerfix-{name}.bin'
        cli('-u', '0x08000000', '0x80000', path)
        raw = path.read_bytes()
        record[name+'_backup'] = str(path)
        if len(raw) != 0x80000:
            raise RuntimeError('Incomplete private Flash capture')
        return raw

    def outputs(slot):
        tokens = []
        for address in ADDRESSES:
            tokens.extend(('-r32', hex(address), '4'))
        return require_registers(cli(*tokens), slot)

    try:
        before = capture('before')
        record['baseline'] = baseline(before)
        record['before_outputs'] = outputs('B')
        import serial
        port = serial.Serial(port=None, baudrate=115200, timeout=.02, write_timeout=2)
        port.dtr = port.rts = False
        port.port = 'COM5'
        port.open()
        uart = Console(port)
        record['before_fw'] = require_confirmed(uart.query('FW STATUS'), 'B')
        if int(record['before_fw']['GEN']) != 420:
            raise RuntimeError('UART/Flash baseline mismatch')
        record['before_zero'] = require_service(uart.query('ZERO STATUS'))
        record['before_switch'] = require_switch(uart.query('SWITCH STATUS'))
        if args.inspect:
            record['pass_'] = True
            print('READ-ONLY PASS: exact original A backed up, B confirmed and OFF', flush=True)
            return
        stage(uart, IMAGE, DEFAULT_CLIENT, allow_reset=False)
        record['staged_flash'] = compare_flash(before, capture('staged'), data, 'A', staged=True)
        record['staged_outputs'] = outputs('B')
        try:
            uart.command('FW END', 20)
        except TimeoutError:
            print('Commit ACK uncertain; observe once, never resend', flush=True)
        record['confirmed'] = observe_trial(uart, 'A')
        record['fresh_switch'] = require_switch(uart.query('SWITCH STATUS'))
        record['start_guard'] = require_switch(uart.query('SWITCH START GUARD'), mode=4)
        time.sleep(.25)  # No SWD or UART polling while timer is active.
        record['guard_line'] = uart.query('SWITCH STATUS')
        # Read back everything even when guard fails. Never start PWM/bridge.
        record['final_outputs'] = outputs('A')
        record['final_fw'] = require_confirmed(uart.query('FW STATUS'), 'A')
        record['final_flash'] = compare_flash(before, capture('final'), data, 'A')
        record['guard'] = guard_result(record['guard_line'])
        record['pass_'] = True
        print('TIMERFIX PASS: independent cutoff qualified; all outputs OFF; switching NOT tested', flush=True)
    except BaseException as error:
        record['failure'] = str(error)
        raise
    finally:
        if uart:
            record['uart'] = uart.lines
        if port:
            port.close()
        target.write_text(json.dumps(record, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
        print('Evidence: '+str(target), flush=True)


if __name__ == '__main__':
    main()
