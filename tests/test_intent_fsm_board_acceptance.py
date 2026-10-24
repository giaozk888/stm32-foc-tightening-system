"""Files/mocks only: candidate identity and no-retry/preflight gates."""
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import intent_fsm_board_acceptance as board


class IntentBoardTests(unittest.TestCase):
    def test_pinned_files_and_no_device_default(self):
        self.assertEqual(len(board.image()), 229220)
        self.assertEqual(board.old.zero.latest_meta(board.baseline())[2:6], (2, 0, 0, 725))
        p = subprocess.run([sys.executable, str(ROOT / 'tools/intent_fsm_board_acceptance.py')],
                           capture_output=True, text=True)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertIn('no devices', p.stdout)

    def test_fresh_state_required_before_device_access(self):
        with patch.object(board.hw, 'debug') as debug, patch.object(board.support, 'open_port') as serial:
            with self.assertRaises(ValueError):
                board.stage({}, 'unused', b'')
            with self.assertRaises(ValueError):
                board.execute({}, 'unused', ROOT / 'tmp/unused.json', b'')
            with self.assertRaises(ValueError):
                board.restore({}, 'unused', ROOT / 'tmp/unused.json', b'')
            debug.assert_not_called()
            serial.assert_not_called()

    def test_failed_health_does_not_start(self):
        row = dict(powered_no_alarm=True, steps=[], commands=[])
        port = Mock()
        uart = Mock()
        with patch.object(board, 'staged_input', return_value=(ROOT / 'tmp/unused.bin', b'capture')), \
             patch.object(board.support, 'open_port', return_value=port), \
             patch.object(board.old.prior, 'JournalConsole', return_value=uart), \
             patch.object(board.hw, 'debug'), \
             patch.object(board.old.prior, 'wait_health_confirmation', side_effect=RuntimeError('health failed')), \
             patch.object(board.old.prior, 'motion') as motion, \
             patch.object(board.old, 'capture_stopped') as capture:
            with self.assertRaisesRegex(RuntimeError, 'health failed'):
                board.execute(row, 'unused', ROOT / 'tmp/unused.json', b'image')
            motion.assert_not_called()
            capture.assert_called_once()

    def test_failed_timing_does_not_start(self):
        row = dict(powered_no_alarm=True, steps=[], commands=[])
        uart = Mock(lines=['TIGHTEN: INTENT_FSM_CANDIDATE; manual START only'])
        uart.query.return_value = '1 OK'
        with patch.object(board, 'staged_input', return_value=(ROOT / 'tmp/unused.bin', b'capture')), \
             patch.object(board.support, 'open_port', return_value=Mock()), \
             patch.object(board.old.prior, 'JournalConsole', return_value=uart), \
             patch.object(board.hw, 'debug'), \
             patch.object(board.old.prior, 'wait_health_confirmation'), \
             patch.object(board.old.zero, 'zero_fields'), patch.object(board, 'check_profile'), \
             patch.object(board.old.prior, 'wait_timing', side_effect=RuntimeError('deadline')), \
             patch.object(board.old.prior, 'motion') as motion, \
             patch.object(board.old, 'capture_stopped'):
            with self.assertRaisesRegex(RuntimeError, 'deadline'):
                board.execute(row, 'unused', ROOT / 'tmp/unused.json', b'image')
            motion.assert_not_called()


if __name__ == '__main__':
    unittest.main()
