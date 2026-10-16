import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'tools'))
import switch_feedback_timerfix_acceptance as host


class TimerFixTests(unittest.TestCase):
    def test_pinned_image(self):
        self.assertEqual(host.image_info(host.image())[0], 'A')

    def test_cutoff_boundaries_and_output_off(self):
        good = ('1 OK SWITCH PROFILE=OPEN_LOAD_ONLY MOTOR_READY=0 ACTIVE=0 MODE=4 '
                'REASON=2 N=0 US=190000 DONE=16 IRQ=1 IRQ_SR=1 SD=0 MOE=0 CCER=0 CEN=0')
        host.guard_result(good)
        for old, new in (('US=190000', 'US=1'), ('IRQ=1', 'IRQ=2'),
                         ('IRQ_SR=1', 'IRQ_SR=0'), ('DONE=16', 'DONE=0'),
                         ('SD=0', 'SD=1'), ('N=0', 'N=1')):
            with self.assertRaises(RuntimeError):
                host.guard_result(good.replace(old, new))

    def test_no_switching_or_forced_recovery(self):
        source = Path(host.__file__).read_text()
        for forbidden in ('SWITCH START PWM', 'SWITCH START BRIDGE', 'ZERO SAMPLE',
                          'SWITCH WAVE VERIFIED', 'FW CONFIRM', 'BOOT A', "cli('-rst')"):
            self.assertNotIn(forbidden, source)
        self.assertIn("compare_flash(before, capture('staged'), data, 'A', staged=True)", source)
        self.assertIn("observe_trial(uart, 'A')", source)


if __name__ == '__main__':
    unittest.main()
