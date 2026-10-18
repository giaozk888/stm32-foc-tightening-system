"""Offline runner gates; never access a serial port, debugger or private data."""
import json
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
import encoder_foc_first_board_test as board


class EncoderBoardTests(unittest.TestCase):
    def test_image_pins(self):
        self.assertEqual(len(board.image()), 228964)
        with patch.object(board, 'SHA', '0'*64), self.assertRaises(ValueError): board.image()

    def test_offline_schema_and_stage_bounds(self):
        code = ('import encoder_foc_first_board_test as b,json; from unittest.mock import patch; '
                'b.configure(); '
                'm=patch.object(b.base.tx,"baseline",return_value=(None,b"")); '
                'm.start(); b.verify(); m.stop(); '
                'print(json.dumps(b.base.tx.stage_commands(b.PRIVATE/"live.bin",'
                'b.PRIVATE/"expected.bin",b.PRIVATE/"staged.bin")))')
        p = subprocess.run([sys.executable, '-c', code], cwd=board.ROOT/'tools',
                           capture_output=True, text=True, timeout=30)
        self.assertEqual(p.returncode, 0, p.stderr)
        commands = json.loads(p.stdout)
        self.assertTrue(any('EncoderReview/EncoderFocFirst/foc2.bin' in c and
                            '0x08008000 bin' in c for c in commands))
        self.assertTrue(any('verify_image' in c for c in commands))
        self.assertFalse(any(c in ('resume', 'reset run') or '0x2001FFC0' in c for c in commands))

    def test_physical_gate_before_device_access(self):
        for mode in ('--stage-inactive-a','--trial-from-stage','--restore-from-trial'):
            args = [mode] + ([] if mode == '--stage-inactive-a' else ['unused.json'])
            p = subprocess.run([sys.executable, str(board.ROOT/'tools/encoder_foc_first_board_test.py'),
                                *args], capture_output=True, text=True, timeout=30)
            self.assertNotEqual(p.returncode, 0)
            self.assertIn('disconnected motor required', p.stderr)

    def test_acceptance_rejects_bad_inventory_and_false_preemption(self):
        p = dict(encoder_priority_verified=True, timing=dict(preempt_max_us=0),
                 encoder_events=dict(deferred_service_count=10, rx_event_count=4,
                                     period_count=2, tx_error_count=0))
        self.assertIsNone(board.acceptance_failure(p))
        p['timing']['preempt_max_us'] = 1
        self.assertIsNotNone(board.acceptance_failure(p))
        p['timing']['preempt_max_us'] = 0
        p['encoder_priority_verified'] = False
        self.assertIsNotNone(board.acceptance_failure(p))


if __name__ == '__main__': unittest.main()
