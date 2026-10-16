"""Read a frozen hard-off repair window. Default is offline; never resets/starts.

Deploy the separate RepairWindowDiagnostic profile before --read-frozen.
Reading an old/non-frozen profile fails closed, without any retry or mutation.
"""
import argparse
import json
from pathlib import Path
import time

import zero_all_rejected_board_test as base

COMMANDS = frozenset(('MOTOR TEST REPAIR',)) | frozenset(
    'MOTOR TEST REPAIR ROW ' + str(i) for i in range(32))


class Console(base.Console):
    READ = base.Console.READ | COMMANDS | frozenset(('MOTOR TEST COMPACT',))

    def query(self, text, timeout=2):
        if text not in self.READ:
            raise ValueError('Read only; no reset, START, stop, trial or clear')
        return super().query(text, timeout)


def validate(summary, rows):
    """Audit sequence, both repair channels, exact bit window and stop cause."""
    def number(s, key):
        return int(s[key], 16 if key == 'WIN' else 10)
    for key, value in dict(ENABLED='1', HARD_OFF='1', N='32', FROZEN='1', GAP='0').items():
        if summary.get(key) != value:
            raise ValueError('Missing immutable, gap-free hard-off trace: ' + key)
    count = number(summary, 'COUNT')
    if count != 32 or len(rows) != count:
        raise ValueError('A full 32-pair repair fault window is required')
    last = number(summary, 'SEQ')
    bits = streak = 0
    for i, row in enumerate(rows):
        seq = (last - count + 1 + i) & 0xffffffff
        if number(row, 'I') != i or number(row, 'SEQ') != seq:
            raise ValueError('Non-contiguous physical input sequence')
        if row.get('READY') != '1' or number(row, 'SRC') != (seq - 1) & 0xffffffff:
            raise ValueError('Four-point selector source alignment mismatch')
        mask = number(row, 'MASK')
        if not 0 <= mask <= 3:
            raise ValueError('Invalid U/V repair mask')
        for key, limit in (('RAW', 4095), ('FILTER', 4095), ('JUMP', 63)):
            pair = [int(v) for v in row[key].split(',')]
            if len(pair) != 2 or any(not 0 <= v <= limit for v in pair):
                raise ValueError('Invalid packed pair: ' + key)
        bits = ((bits << 1) | bool(mask)) & 0xffffffff
        streak = streak + 1 if mask else 0
    hits = bits.bit_count()
    if (bits != number(summary, 'WIN') or hits != number(summary, 'HITS')
            or streak != number(summary, 'STREAK')):
        raise ValueError('Exported masks disagree with the actual protection counters')
    cause = int(hits > number(summary, 'LIMIT')) | (int(streak > number(summary, 'SLIMIT')) << 1)
    if number(summary, 'REASON') != 9 or not cause or cause != number(summary, 'CAUSE'):
        raise ValueError('Not a consistent repair-budget fault')
    if not 0 <= number(summary, 'US') <= 0xffffffff or number(summary, 'TOTAL') < hits:
        raise ValueError('Invalid fault timestamp or cumulative count')
    return dict(capture_valid=True, pairs=count, window_hits=hits, consecutive=streak,
        window_limit=number(summary, 'LIMIT'), streak_limit=number(summary, 'SLIMIT'),
        cause={1: 'WINDOW', 2: 'STREAK', 3: 'WINDOW_AND_STREAK'}[cause],
        timing_acceptance=False, motor_acceptance=False)


def collect(uart, evidence):
    # Save each response immediately so a partial read is not mislabeled complete.
    summary_line = uart.query('MOTOR TEST REPAIR')
    evidence['summary_line'] = summary_line
    summary = evidence['summary'] = base.fields(summary_line)
    if any(summary.get(k) != v for k, v in dict(ENABLED='1', HARD_OFF='1',
            N='32', FROZEN='1', COUNT='32', GAP='0', REASON='9').items()):
        raise ValueError('No full frozen repair fault; do not reset or retry automatically')
    rows = evidence['rows'] = []
    evidence['row_lines'] = []
    for i in range(32):
        line = uart.query('MOTOR TEST REPAIR ROW ' + str(i))
        evidence['row_lines'].append(line)
        rows.append(base.fields(line))
    # Re-read the identity and counters to catch a reset or incoherent export.
    again = base.fields(uart.query('MOTOR TEST REPAIR'))
    evidence['summary_after'] = again
    if again != summary:
        raise ValueError('Frozen trace changed while reading')
    result = validate(summary, rows)
    state = evidence['state'] = base.fields(uart.query('MOTOR TEST STATUS'))
    if any(state.get(k) != v for k, v in dict(SD='0', MOE='0', CCER='0', FAULT='1', STATE='4').items()):
        raise ValueError('Fault/output-lock state not established')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--read-frozen', action='store_true')
    args = parser.parse_args()
    if not args.read_frozen:
        print('OFFLINE: repair window reader ready; no hardware/private access')
        return
    evidence = dict(capture_valid=False, motor_commands=0, resets=0, flash_writes=0,
                    automatic_retry=False, timing_acceptance=False, motor_acceptance=False)
    port = uart = None
    try:
        port = base.open_port()
        uart = Console(port)
        evidence.update(collect(uart, evidence))
        print('CAPTURE PASS: ' + evidence['cause'] + '; not motor/timing acceptance')
    except Exception as error:
        evidence.update(capture_valid=False, failure=str(error))
        print('CAPTURE INCOMPLETE: ' + str(error))
    finally:
        if uart:
            evidence['uart'] = uart.lines
        if port and port.is_open:
            port.close()
        output = base.OUTPUT / ('repair-window-read-' + str(time.time_ns()) + '.json')
        output.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        print('Evidence: ' + str(output))


if __name__ == '__main__':
    main()
