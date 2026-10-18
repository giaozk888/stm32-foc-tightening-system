"""Host-only motion runner cases: completion, early abort and cleanup."""
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import loaded_fsm_motion as runner

RECIPE = dict(zip(runner.RECIPE_NAMES, (
    70, 10, 300, 250, 8000, 3000, 80, 100, 120, 150, 150,
    300, 300, 300, 300, 500, 30, 90)))


class FakeBoard:
    def __init__(self, stages, fault=False):
        self.recipe = dict(RECIPE)
        self.commands = []
        self.stage_iter = iter(stages)
        self.queued = []
        self.count = 100
        self.fault = fault

    def command(self, command, *args):
        self.commands.append(command)
        if command == 'MOTOR TEST PROFILE':
            return ('OK NAME=PROTECTED_PIPELINE_CLOSED_LOOP HARD_OFF=0 FSM=ORIGINAL '
                    'PIPELINE=1 RPM=20 LEASE_US=12000000')
        if command == 'MOTOR TEST STATUS':
            return 'OK STATE=1 USED=0 ZERO=3 FAULT=0 SD=0 MOE=0 CCER=0'
        if command.startswith('GET '):
            key = command.split()[1]
            return 'OK %s=%s' % (key, self.recipe[key])
        if command.startswith('SET '):
            _, key, value = command.split()
            self.recipe[key] = int(value)
        if command == 'ANALOG SAFE STATUS':
            return 'OK LATCHED=1 SD=0 MOE=0 FOC=0'
        return 'OK'

    def send(self, command):
        self.commands.append(command)
        self.count += 1
        if command == 'START':
            self.queued.append('%s OK START QUEUED' % self.count)
        elif command == 'STATUS':
            stage = next(self.stage_iter, 9)
            outcome = 'OK' if stage == 9 else 'NONE'
            self.queued.append('%s OK STATUS STAGE=%s BUSY=%s FLT=%s OUTCOME=%s CONTACT=1'
                               % (self.count, stage, int(stage != 9), int(self.fault), outcome))
        return self.count

    def read_line(self, *args):
        return self.queued.pop(0) if self.queued else None


class LoadedMotionTests(unittest.TestCase):
    def run_fake(self, board):
        clock = iter(i * .01 for i in range(20000))
        record = dict(postflight={}, samples=[])
        with patch.object(runner, 'require_idle_ready'), \
                patch.object(runner.time, 'monotonic', side_effect=lambda: next(clock)), \
                patch.object(runner, 'stop', side_effect=lambda b: b.command('STOP')):
            runner.execute(board, record, 'B')
        return record

    def test_complete_cycle_once_and_recipe_restore(self):
        board = FakeBoard([1, 2, 3, 4, 5, 6, 7, 9])
        record = self.run_fake(board)
        self.assertTrue(record['cycle_pass'])
        self.assertEqual(board.commands.count('START'), 1)
        self.assertEqual(board.recipe, RECIPE)
        self.assertLess(board.commands.index('ANALOG SAFE'),
                        board.commands.index('SET RUNDOWN_RPM 70'))

    def test_fault_stops_and_latches_without_second_start(self):
        board = FakeBoard([1], fault=True)
        with self.assertRaisesRegex(RuntimeError, 'Fault during cycle'):
            self.run_fake(board)
        self.assertEqual(board.commands.count('START'), 1)
        self.assertIn('STOP', board.commands)
        self.assertIn('ANALOG SAFE', board.commands)
        self.assertEqual(board.recipe, RECIPE)

    def test_missing_stage_is_not_full_cycle_pass(self):
        board = FakeBoard([1, 2, 9])
        with self.assertRaisesRegex(RuntimeError, 'stages not observed'):
            self.run_fake(board)
        self.assertIn('ANALOG SAFE', board.commands)

    def test_excessive_recipe_never_starts(self):
        board = FakeBoard([])
        board.recipe['RUNDOWN_TIMEOUT_MS'] = 20000
        with self.assertRaises(ValueError):
            self.run_fake(board)
        self.assertNotIn('START', board.commands)
        self.assertIn('ANALOG SAFE', board.commands)


if __name__ == '__main__':
    unittest.main()
