"""One original tightening cycle with the separate 12 s / 20 rpm profile.

Default is read-only. The caller checks the connected, secured workpiece and
drive before --execute. Never clears faults, repeats START or saves a recipe.
"""
import argparse
import json
from pathlib import Path
import time

from firmware_transfer_iap import fields
from motor_motion_smoke import Board, require_idle_ready, stop

RECIPE_NAMES = (
    'RUNDOWN_RPM', 'CONTACT_RPM', 'CONTACT_IQ_MA', 'CONTACT_MS',
    'RUNDOWN_TIMEOUT_MS', 'MAX_TRAVEL_DEG', 'SEATING_IQ_MA', 'T1_IQ_MA',
    'T2_IQ_MA', 'T3_IQ_MA', 'HOLD_IQ_MA', 'SEATING_MS', 'T1_MS', 'T2_MS',
    'T3_MS', 'HOLD_MS', 'TORQUE_ABORT_RPM', 'POST_TRAVEL_MAX_DEG')
POST_TIMES = ('SEATING_MS', 'T1_MS', 'T2_MS', 'T3_MS', 'HOLD_MS')
EXPECTED_STAGES = {1, 2, 3, 4, 5, 6, 7, 9}
HOST_MAX_SECONDS = 11.95


def check_recipe(recipe):
    if recipe['RUNDOWN_TIMEOUT_MS'] > 8000:
        raise ValueError('Existing rundown timeout exceeds the 12 s trial budget')
    if sum(recipe[key] for key in POST_TIMES) > 1700:
        raise ValueError('Existing post-contact duration exceeds the trial budget')
    if not all(0 < recipe[key] <= 150 for key in
               ('SEATING_IQ_MA', 'T1_IQ_MA', 'T2_IQ_MA', 'T3_IQ_MA', 'HOLD_IQ_MA')):
        raise ValueError('Unexpected post-contact current recipe')


def check_profile(profile, expected_speed_ctrl=None):
    expected = dict(NAME='PROTECTED_PIPELINE_CLOSED_LOOP', HARD_OFF='0',
                    FSM='ORIGINAL', PIPELINE='1', RPM='20', LEASE_US='12000000')
    if any(profile.get(key) != value for key, value in expected.items()):
        raise RuntimeError('Exact loaded original-FSM profile required')
    if expected_speed_ctrl is not None and profile.get('SPEED_CTRL') != expected_speed_ctrl:
        raise RuntimeError('Expected speed-controller candidate marker absent')


class RecordedBoard(Board):
    def __init__(self, port, record):
        self.record = record
        super().__init__(port)

    def send(self, command):
        self.record['commands'].append(dict(at=time.monotonic(), command=command))
        return super().send(command)

    def read_line(self, seconds=0.02):
        line = super().read_line(seconds)
        if line is not None:
            self.record['uart'].append(dict(at=time.monotonic(), line=line))
        return line


def execute(board, record, slot, expected_speed_ctrl=None):
    original_rpm = None
    rpm_may_have_changed = started = False
    try:
        require_idle_ready(board, slot)
        check_profile(fields(board.command('MOTOR TEST PROFILE')),expected_speed_ctrl)
        state = fields(board.command('MOTOR TEST STATUS'))
        if any(state.get(k) != v for k, v in
               (('STATE', '1'), ('USED', '0'), ('ZERO', '3'), ('FAULT', '0'),
                ('SD', '0'), ('MOE', '0'), ('CCER', '0'))):
            raise RuntimeError('Loaded trial not calibrated, ready and unused')
        recipe = {name: int(fields(board.command('GET ' + name))[name])
                  for name in RECIPE_NAMES}
        check_recipe(recipe)
        record['original_recipe'] = recipe
        original_rpm = recipe['RUNDOWN_RPM']
        rpm_may_have_changed = True
        board.command('SET RUNDOWN_RPM 20')
        if fields(board.command('GET RUNDOWN_RPM')).get('RUNDOWN_RPM') != '20':
            raise RuntimeError('20 rpm setpoint readback failed')
        require_idle_ready(board, slot)
        started = True  # A missing ACK does not prove START was unreceived.
        start_id = board.send('START')
        start_at = time.monotonic()
        end = start_at + HOST_MAX_SECONDS
        next_status = start_at + 0.05
        pending = None
        status_sent_at = None
        start_ack = False
        record['stages'] = []
        while time.monotonic() < end:
            now = time.monotonic()
            if pending is None and now >= next_status:
                pending = board.send('STATUS')
                status_sent_at = now
                next_status = now + 0.05
            if pending is not None and now - status_sent_at > 0.3:
                raise TimeoutError('Motion telemetry absent for 300 ms')
            line = board.read_line(min(0.01, max(0, end-time.monotonic())))
            if line is None:
                continue
            if line.startswith(str(start_id) + ' '):
                print(line, flush=True)
                if not line.startswith(str(start_id) + ' OK '):
                    raise RuntimeError('START refused')
                start_ack = True
            elif pending is not None and line.startswith(str(pending) + ' '):
                pending = None
                if ' OK STATUS ' not in line:
                    raise RuntimeError('Invalid status response')
                status = fields(line)
                elapsed = time.monotonic() - start_at
                record['samples'].append(dict(elapsed_s=elapsed, status=status))
                stage = int(status['STAGE'])
                if stage not in record['stages']:
                    record['stages'].append(stage)
                print('T=%.3f %s' % (elapsed, line), flush=True)
                if status.get('FLT') != '0':
                    raise RuntimeError('Fault during cycle; no retry')
                if elapsed > 0.2 and status.get('BUSY') == '0':
                    record['terminal_status'] = status
                    if not start_ack or status.get('OUTCOME') != 'OK':
                        raise RuntimeError('Cycle ended without COMPLETE OK')
                    if status.get('CONTACT') != '1':
                        raise RuntimeError('No contact recorded')
                    missing = EXPECTED_STAGES - set(record['stages'])
                    if missing:
                        raise RuntimeError('Cycle stages not observed: ' + str(sorted(missing)))
                    record['cycle_pass'] = True
                    return
            if not start_ack and time.monotonic() - start_at > 0.3:
                raise TimeoutError('START ACK absent')
        raise TimeoutError('Host cycle deadline reached')
    finally:
        if started:
            try:
                stop(board)
            except Exception as error:
                record['stop_error'] = str(error)
        # Latch off before recipe readback or diagnostics, including on error.
        record['off_ack'] = board.command('ANALOG SAFE', 0.8)
        safe = fields(board.command('ANALOG SAFE STATUS', 0.8))
        record['safe'] = safe
        if any(safe.get(k) != v for k, v in
               (('LATCHED', '1'), ('SD', '0'), ('MOE', '0'), ('FOC', '0'))):
            raise RuntimeError('Output-off latch not verified')
        if rpm_may_have_changed:
            board.command('SET RUNDOWN_RPM ' + str(original_rpm))
            if fields(board.command('GET RUNDOWN_RPM')).get('RUNDOWN_RPM') != str(original_rpm):
                raise RuntimeError('Original recipe rpm restore failed')
            record['recipe_restored'] = True
        for command in ('MOTOR TEST FAULT', 'MOTOR TEST TIMING', 'STATUS'):
            record['postflight'][command] = board.command(command)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', default='COM5')
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--expected-slot', choices=('A', 'B'), default='B')
    parser.add_argument('--expected-speed-ctrl', choices=('SB1',))
    args = parser.parse_args()
    record = dict(cycle_pass=False, torque_accuracy_verified=False,
                  automatic_retry=False, commands=[], uart=[], samples=[], postflight={})
    record['expected_speed_ctrl']=args.expected_speed_ctrl
    receipt = Path(__file__).resolve().parents[1] / 'tmp' / (
        'loaded-fsm-motion-' + str(time.time_ns()) + '.json')
    board = RecordedBoard(args.port, record)
    try:
        if args.execute:
            execute(board, record, args.expected_slot,args.expected_speed_ctrl)
        else:
            require_idle_ready(board, args.expected_slot)
            check_profile(fields(board.command('MOTOR TEST PROFILE')),args.expected_speed_ctrl)
            print('READ ONLY: no START sent')
    except Exception as error:
        record['failure'] = str(error)
        print('FAILED: ' + str(error), flush=True)
    finally:
        board.close()
        receipt.parent.mkdir(exist_ok=True)
        receipt.write_text(json.dumps(record, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        print('Evidence: ' + str(receipt), flush=True)
    return 0 if record.get('cycle_pass') or (not args.execute and 'failure' not in record) else 1


if __name__ == '__main__':
    raise SystemExit(main())
