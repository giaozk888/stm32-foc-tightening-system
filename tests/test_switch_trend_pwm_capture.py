import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
import switch_trend_pwm_capture as host

BASE=('OK PROFILE=OPEN_LOAD_ONLY MOTOR_READY=0 ACTIVE=0 MODE=1 REASON=1 '
      'N=3600 FN=3598 US=179940 DONE=18 ATTEMPTS=18 WAVE=0 SD=0 MOE=0 CCER=0 CEN=0')

class PwmCaptureTests(unittest.TestCase):
    def test_digit_suffix_zero_fields(self):
        self.assertEqual(host.zero_reference('OK U0=1561 V0=1560 N=4000'),(1561,1560))
        for line in ('OK U=1561 V=1560','OK U0=4096 V0=1560','OK U0=1561'):
            with self.assertRaises(RuntimeError): host.zero_reference(line)
    def test_prerequisites(self):
        host.before_capture(BASE)
        for old,new in [('DONE=18','DONE=2'),('ATTEMPTS=18','ATTEMPTS=22'),
                        ('WAVE=0','WAVE=1'),('SD=0','SD=1'),('N=3600','N=10')]:
            with self.assertRaises(RuntimeError): host.before_capture(BASE.replace(old,new))
    def test_active_sd_low(self):
        line='OK PROFILE=OPEN_LOAD_ONLY MOTOR_READY=0 ACTIVE=1 MODE=2 SD=0 MOE=1 CCER=1365 CEN=1'
        host.start_proof(line)
        for old,new in [('SD=0','SD=1'),('CCER=1365','CCER=0'),('MODE=2','MODE=3')]:
            with self.assertRaises(RuntimeError): host.start_proof(line.replace(old,new))
    def test_no_bridge_reset_or_repeat(self):
        class Port:
            def write(self,value): raise TimeoutError('Lost ACK')
        c=host.Console(Port())
        for command in ('SWITCH START BRIDGE','SWITCH START GUARD','SWITCH START OFF',
                        'SWITCH WAVE VERIFIED','ZERO SAMPLE','START','CLEAR'):
            with self.assertRaises(ValueError): c.query(command)
        with self.assertRaises(ValueError): c.command('FW END')
        with self.assertRaises(TimeoutError): c.query('SWITCH START PWM')
        with self.assertRaises(ValueError): c.query('SWITCH START PWM')
    def test_common_reference_no_double_count(self):
        result=host.common_reference([(1561,1560),(1662,1661)],(1561,1560))
        self.assertEqual(result['outside_100_pairs'],1)
        self.assertEqual(result['reference'],[1561,1560])
        self.assertEqual(result['channels'][0]['max_abs_deviation'],101)

if __name__=='__main__': unittest.main()
