import sys
import unittest
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
import switch_trend_compare_deploy as host

class SwitchTrendDeploymentTests(unittest.TestCase):
    def test_image_and_identity(self):
        self.assertEqual(host.image_info(host.image())[0],'B')
        self.assertEqual(len(host.image()),149748)
    def test_baseline_generation_and_slot(self):
        for slot,gen in (('B',443),('A',440),('A',446)):
            with patch.object(host,'locked_baseline',return_value=dict(current=slot,generation=gen)):
                with self.assertRaises(RuntimeError): host.baseline(b'')
        with patch.object(host,'locked_baseline',return_value=dict(current='A',generation=443)):
            self.assertEqual(host.baseline(b'')['generation'],443)
    def test_console_does_not_start_capture_or_power(self):
        class Port:
            def write(self,value): raise TimeoutError('lost ACK')
        uart=host.Console(Port())
        for command in ('START','SWITCH START OFF','SWITCH START PWM','SWITCH START BRIDGE',
                        'SWITCH WAVE VERIFIED','ZERO SAMPLE','CLEAR','BOOT B'):
            with self.assertRaises(ValueError): uart.query(command)
        with self.assertRaises(TimeoutError): uart.query('SWITCH START GUARD')
        with self.assertRaises(ValueError): uart.query('SWITCH START GUARD')
    def test_observer_is_not_admission_or_trip(self):
        core=(ROOT/'firmware_common/switch_feedback_core.h').read_text()
        self.assertIn('s->mode == SWITCH_BRIDGE && trip',core)
        diag=(ROOT/'firmware_common/switch_feedback_diag.inc').read_text()
        gate=diag[diag.index('uint8_t admitted ='):diag.index('if (admitted) {')]
        self.assertNotIn('trend_',gate)
        self.assertIn('zero_median.raw.state == FOC_ZERO_READY',gate)
        self.assertIn('switch_wave_verified &&',gate)
        self.assertIn('POLICY=OBSERVER_ONLY',diag)

if __name__=='__main__': unittest.main()
