"""Read-only arithmetic for an already captured PWM-boundary receipt.

This is not hardware-edge timing, a WCET proof, or actuation qualification.
It never accesses serial, debugger, private Flash, or motor commands.
"""
import argparse
import json
from pathlib import Path

TIMER_HZ = 170_000_000
ARR = 4249
PERIOD_TICKS = 2 * ARR
GUARD_TICKS = 170


def assess(sample):
    adc = sample['adc']
    boundary = sample['boundary']
    if (adc.get('DWT') != '1' or boundary.get('HW_VERIFIED') != '0' or
            boundary.get('PAIRS') != adc.get('PAIRS')):
        raise ValueError('Expected unverified 170 MHz boundary-lite snapshot')
    frames = {}
    for name in ('first','worst'):
        row = sample[name]
        if row.get('VALID') != '1' or row.get('HW_VERIFIED') != '0':
            raise ValueError('A valid software frame is required')
        rem, wall, over = (int(row[key]) for key in ('REM','WALL','OVER'))
        if not 0 < rem <= PERIOD_TICKS or wall-rem != over or over <= 0:
            raise ValueError('Inconsistent timer/DWT frame')
        frames[name] = {
            'sequence': int(row['SEQ']),
            'remaining_us': rem * 1_000_000 / TIMER_HZ,
            'observed_wall_us': wall * 1_000_000 / TIMER_HZ,
            'current_bottom_deficit_us': (wall + GUARD_TICKS - rem) * 1_000_000 / TIMER_HZ,
            'next_bottom_budget_us': (rem + PERIOD_TICKS - GUARD_TICKS) * 1_000_000 / TIMER_HZ,
        }
    return {
        'samples': int(adc['PAIRS']),
        'coarse_late': int(boundary['LATE']),
        'observed_irq_max_us': int(adc['MAX_CYC']) * 1_000_000 / TIMER_HZ,
        'period_us': PERIOD_TICKS * 1_000_000 / TIMER_HZ,
        'frames': frames,
        'caution': 'Next-bottom budget is geometry only; no active-CCR, ISR-tail, noise or WCET proof.'
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('public_receipt',type=Path)
    args = parser.parse_args()
    row = json.loads(args.public_receipt.read_text('utf-8'))
    if row.get('mode') != 'trial' or row.get('image_sha256') != \
            '2c5fecc39d6649a08da49cffba26d63fd77614a590b26eb5d8f5451abc3be8fc':
        raise ValueError('Expected exact boundary-lite trial receipt')
    print(json.dumps(assess(row['sample']),ensure_ascii=False,indent=2))


if __name__ == '__main__':
    main()
