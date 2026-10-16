"""One powered open-load baseline on pinned confirmed repaired A.

No reset, Flash write, zero calibration, PWM or bridge command. TIM1 only
triggers the dual injected ADC while SD/MOE/CCER remain OFF. Replay saved
samples after the bounded capture, never poll/probe during acquisition.
"""
import argparse
import json
import re
import statistics
import subprocess
import time

from firmware_transfer_iap import fields
from switch_feedback_acceptance import Console, require_switch
from switch_feedback_timerfix_acceptance import OUTPUT, SHA, ORIGINAL_B, image, guard_result
from zero_async_clock_acceptance import locked_baseline
from zero_retest_deploy import CLI, SN, require_confirmed, require_service
from zero_span100_acceptance import ADDRESSES, require_registers


class OffConsole(Console):
    def command(self, *args, **kwargs):
        raise ValueError('Firmware transfer/reset forbidden in capture')

    def query(self, text, timeout=2):
        if text not in ('FW STATUS', 'ZERO STATUS', 'ZERO FILTER STATUS', 'ANALOG VOLT',
                        'SWITCH STATUS', 'SWITCH START OFF', 'SWITCH ABORT') and not re.fullmatch(r'SWITCH READ \d+', text):
            raise ValueError('Only one output-OFF acquisition and read-only queries admitted')
        return super().query(text, timeout)


def analyze(samples, row):
    n = int(row['N'])
    if not n or n > 3600 or len(samples) != n:
        raise RuntimeError('Complete bounded raw replay required')
    if any(not 0 <= value <= 4095 for pair in samples for value in pair):
        raise RuntimeError('Invalid ADC code in replay')
    filtered = [(sorted(x[0] for x in samples[i-2:i+1])[1],
                 sorted(x[1] for x in samples[i-2:i+1])[1]) for i in range(2, n)]
    totals = tuple(sum(pair[ch] for pair in samples) for ch in (0, 1))
    ftotals = tuple(sum(pair[ch] for pair in filtered) for ch in (0, 1))
    if (totals != tuple(map(int, row['SUM'].split(','))) or
            ftotals != tuple(map(int, row['FSUM'].split(','))) or len(filtered) != int(row['FN'])):
        raise RuntimeError('Raw/median replay differs from ISR accumulation')
    zero = tuple(map(int, row['ZERO'].split(',')))
    channels = {}
    for ch, name in enumerate(('IU', 'IV')):
        raw = [pair[ch] for pair in samples]
        med = [pair[ch] for pair in filtered]
        outside = [i for i, value in enumerate(raw) if abs(value-zero[ch]) > 100]
        channels[name] = dict(mean=statistics.mean(raw), minimum=min(raw), maximum=max(raw),
                              stddev=statistics.pstdev(raw), zero_reference=zero[ch],
                              max_abs_deviation=max(abs(x-zero[ch]) for x in raw),
                              outside_100=len(outside), outside_indices=outside,
                              median_mean=statistics.mean(med) if med else None,
                              median_minimum=min(med) if med else None,
                              median_maximum=max(med) if med else None,
                              median_outside_100=sum(abs(x-zero[ch]) > 100 for x in med))
    pair_outside = sum(any(abs(pair[ch]-zero[ch]) > 100 for ch in (0, 1)) for pair in samples)
    if pair_outside != int(row['OUT']):
        raise RuntimeError('Outside count mismatch')
    return dict(channels=channels, pair_outside_100=pair_outside,
                sample_pairs=n, elapsed_us=int(row['US']),
                mean_pair_rate_hz=n * 1e6/int(row['US']) if int(row['US']) else None,
                nominal_reference_not_published_calibration=True,
                motor_current_accuracy_qualified=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--powered-open-load-ready', action='store_true')
    args = parser.parse_args()
    if not args.powered_open_load_ready:
        parser.error('12 V, 0.5 A supply limit, disconnected U/V/W required')
    image()  # Pin the expected offline artifact before any hardware access.
    private = OUTPUT/'private'
    private.mkdir(exist_ok=True)
    subprocess.run(['icacls', str(private), '/inheritance:r', '/grant:r',
                    '*S-1-5-18:(OI)(CI)F', '*S-1-5-32-544:(OI)(CI)F'],
                   check=True, capture_output=True)
    run = str(time.time_ns())
    target = OUTPUT/f'off-repaired-a-{run}.json'
    record = dict(pass_=False, mode='OUTPUT_OFF', image_sha256=SHA, resets=0,
                  flash_writes=0, pwm_enabled=False, bridge_enabled=False,
                  motion_commands=False, automatic_retry=False, steps=[])
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

    def outputs():
        tokens = []
        for address in ADDRESSES:
            tokens.extend(('-r32', hex(address), '4'))
        return require_registers(cli(*tokens), 'A')

    try:
        record['before_outputs'] = outputs()
        backup = private/f'{run}-off-identity.bin'
        cli('-u', '0x08000000', '0x80000', backup)
        record['identity_backup'] = str(backup)
        base = locked_baseline(backup.read_bytes(), known={'A': frozenset((SHA,)),
                                                         'B': frozenset((ORIGINAL_B,))})
        if base['current'] != 'A' or base['generation'] != 423:
            raise RuntimeError('Exact confirmed repaired A generation 423 required')
        record['baseline'] = base
        import serial
        port = serial.Serial(port=None, baudrate=115200, timeout=.02, write_timeout=2)
        port.dtr = port.rts = False
        port.port = 'COM5'
        port.open()
        uart = OffConsole(port)
        record['before_fw'] = require_confirmed(uart.query('FW STATUS'), 'A')
        if int(record['before_fw']['GEN']) != 423:
            raise RuntimeError('UART/Flash identity mismatch')
        record['before_zero'] = require_service(uart.query('ZERO STATUS'))
        record['before_switch'] = guard_result(uart.query('SWITCH STATUS'))
        record['analog_before'] = uart.query('ANALOG VOLT')
        record['start'] = uart.query('SWITCH START OFF')
        time.sleep(.25)  # Do not poll UART or probe SWD during acquisition.
        record['capture_line'] = uart.query('SWITCH STATUS')
        row = require_switch(record['capture_line'], mode=1)
        if row.get('ACTIVE') != '0':
            uart.query('SWITCH ABORT')
            raise RuntimeError('Capture still active past cutoff; aborted, no retry')
        record['capture'] = row
        record['final_outputs'] = outputs()
        n = int(row['N'])
        if not 0 <= n <= 3600:
            raise RuntimeError('Capture index bound violated')
        record['samples'] = samples = []
        for index in range(n):
            pair = fields(uart.query(f'SWITCH READ {index}'))
            if pair.get('I') != str(index):
                raise RuntimeError('Raw replay index mismatch')
            samples.append((int(pair['U']), int(pair['V'])))
            if (index+1) % 900 == 0:
                print(f'Replayed {index+1}/{n} saved pairs; outputs OFF', flush=True)
        if n:
            record['analysis'] = analyze(samples, row)
        record['final_fw'] = require_confirmed(uart.query('FW STATUS'), 'A')
        record['after_switch'] = require_switch(uart.query('SWITCH STATUS'), mode=1)
        require_switch(record['capture_line'], mode=1, complete=True)
        record['pass_'] = True
        print('OFF CAPTURE PASS: raw replay verified; PWM/bridge NOT enabled', flush=True)
        print(json.dumps(record['analysis']['channels'], ensure_ascii=False), flush=True)
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
