import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'tools'))
import switch_feedback_off_capture as host


class OffCaptureTests(unittest.TestCase):
    def test_only_off_and_read_commands(self):
        console = host.OffConsole(None)
        for command in ('SWITCH START PWM', 'SWITCH START BRIDGE', 'ZERO SAMPLE',
                        'SWITCH WAVE VERIFIED', 'FW END', 'START', 'CLEAR', 'BOOT A'):
            with self.assertRaises(ValueError):
                console.query(command)
        with self.assertRaises(ValueError):
            console.command('FW END')

    def test_replay_matches_core(self):
        samples = [(1500, 1550), (2000, 1551), (1501, 1552), (1502, 1553)]
        row = dict(N='4', FN='2', SUM='6503,6206', FSUM='3003,3103',
                   ZERO='1500,1550', OUT='1', US='200')
        out = host.analyze(samples, row)
        self.assertEqual(out['channels']['IU']['outside_100'], 1)
        self.assertEqual(out['channels']['IU']['median_outside_100'], 0)
        self.assertFalse(out['motor_current_accuracy_qualified'])
        with self.assertRaises(RuntimeError):
            host.analyze(samples, dict(row, SUM='0,0'))

    def test_no_reset_or_flash_operations(self):
        source = Path(host.__file__).read_text()
        for forbidden in ('stage(', 'FW END', 'SWITCH START PWM', 'SWITCH START BRIDGE',
                          'ZERO SAMPLE', "cli('-rst')", 'SWITCH WAVE VERIFIED'):
            self.assertNotIn(forbidden, source)


if __name__ == '__main__':
    unittest.main()
