import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'tools'))
import switch_feedback_zero_check as host


class ZeroCheckTests(unittest.TestCase):
    def test_no_output_or_reset_command_admission(self):
        console = host.ZeroConsole(None)
        for command in ('SWITCH START PWM', 'SWITCH START BRIDGE', 'START', 'CLEAR',
                        'SWITCH WAVE VERIFIED', 'FW END', 'BOOT B'):
            with self.assertRaises(ValueError):
                console.query(command)
        with self.assertRaises(ValueError):
            console.command('FW END')

    def test_one_zero_request_never_resends(self):
        console = host.ZeroConsole(None)
        console.starts.add('ZERO SAMPLE')
        with self.assertRaises(ValueError):
            console.query('ZERO SAMPLE')

    def test_raw_quality_not_bypassed(self):
        source = Path(host.__file__).read_text()
        self.assertIn("filtered.get('RAW_STATE') == '3'", source)
        self.assertIn("filtered.get('OUT') == '0'", source)
        self.assertNotIn('stage(', source)
        self.assertNotIn("cli('-rst')", source)


if __name__ == '__main__':
    unittest.main()
