"""Read-only proof of the single pinned fast-math trial's automatic rollback."""
import json
import time

import protected_fast_math_stage as profile
import protected_irq_optimized_stage as old
from protected_irq_timing_acceptance import TimingConsole
from firmware_transfer_iap import fields
from zero_retest_deploy import latest_meta, require_confirmed

FAILURE = profile.OUTPUT / 'irq-compute-1791965830441873200.json'


def main():
    failed = json.loads(FAILURE.read_text('utf-8'))
    if (failed.get('pass_') is not False or failed.get('image_sha256') != profile.SHA or
            failed.get('host_trial_commits') != 1 or failed.get('host_motor_commands') != 0 or
            not failed.get('final_outputs_off') or failed.get('cleanup_failure') or
            failed.get('startup_sample', {}).get('state', {}).get('FLAGS') != '256'):
        raise RuntimeError('Exact stopped fast-math failure receipt required')
    run = str(time.time_ns())
    out = profile.OUTPUT / f'fast-math-rollback-{run}.json'
    row = dict(pass_=False, failure_receipt=str(FAILURE), image_sha256=profile.SHA,
               steps=[], motor_commands=0, resets=0)
    board = profile.Board(row, run)
    port = None
    try:
        port = profile.open_port()
        uart = TimingConsole(port)
        row['fw'] = require_confirmed(uart.query('FW STATUS'), 'A')
        row['safe'] = safe = fields(uart.query('ANALOG SAFE STATUS'))
        if any(safe.get(k) != v for k, v in
               (('LATCHED', '1'), ('SD', '0'), ('MOE', '0'), ('FOC', '0'))):
            raise RuntimeError('Fallback not output-locked')
        row['status'] = uart.query('STATUS')
        if fields(row['status']).get('FLT') != '0':
            raise RuntimeError('Fallback has a fault')
        row['outputs'] = board.outputs('A', False)
        before = old.previous.private_capture(failed, 'before_trial')
        actual = board.capture('rollback')
        if actual[:0x7E800] != before[:0x7E800] or actual[0x7F800:] != before[0x7F800:]:
            raise RuntimeError('Application/private Flash bytes changed')
        prior, current = latest_meta(before), latest_meta(actual)
        if (prior[2:6] != (1, 0, 0, 494) or current[:2] != prior[:2] or
                current[2:6] != (1, 0, 0, 498) or current[6:8] != prior[6:8] or
                current[8:10] != (0, 0) or row['fw'].get('GEN') != '498'):
            raise RuntimeError('Failed-B invalidation/rollback metadata differs')
        row['all_app_and_private_bytes_unchanged'] = True
        row['failed_b_not_bootable_without_new_staging'] = True
        row['uart'] = uart.lines
        row['pass_'] = True
    except BaseException as error:
        row['failure'] = str(error)
        raise
    finally:
        if port:
            port.close()
        out.write_text(json.dumps(row, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        print(('ROLLBACK PASS' if row['pass_'] else 'ROLLBACK FAIL') + '; read only')
        print('Evidence: ' + str(out))


if __name__ == '__main__':
    main()
