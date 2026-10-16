import json
import sys
import unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
import switch_trend_off_capture as host

class SwitchTrendCaptureTests(unittest.TestCase):
    def test_actual_c_replay(self):
        p=ROOT/'safety_backups/switch-feedback-20261012/off-repaired-a-1791801336398511500.json'
        r=host.trend_replay(json.loads(p.read_text('utf-8'))['samples'])
        self.assertEqual(r['N'],3597)
        self.assertEqual(r['REPAIR'],[33,35])
        self.assertEqual(r['RANGE'],[[1524,1610],[1515,1611]])
    def test_board_stats_must_match(self):
        pairs=[(1560,1560)]*4
        good=('OK POLICY=OBSERVER_ONLY MOTOR_READY=0 DELAY_PAIRS=1 N=1 SUM=1560,1560 '
              'RANGE=1560:1560,1560:1560 REPAIR=0,0')
        host.require_trend(good,pairs)
        for old,new in (('N=1','N=2'),('SUM=1560,1560','SUM=1561,1560'),
                        ('POLICY=OBSERVER_ONLY','POLICY=CONTROL')):
            with self.assertRaises(RuntimeError): host.require_trend(good.replace(old,new),pairs)
    def test_no_pwm_bridge_or_reset(self):
        class Port:
            def write(self,value): raise TimeoutError('lost ACK')
        c=host.Console(Port())
        for cmd in ('SWITCH START PWM','SWITCH START BRIDGE','SWITCH WAVE VERIFIED','ZERO SAMPLE','START'):
            with self.assertRaises(ValueError): c.query(cmd)
        with self.assertRaises(ValueError): c.command('FW END')
        with self.assertRaises(TimeoutError): c.query('SWITCH START OFF')
        with self.assertRaises(ValueError): c.query('SWITCH START OFF')

if __name__=='__main__': unittest.main()
