import sys
import unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
import switch_trend_b_zero_check as host

class BZeroTests(unittest.TestCase):
    def test_qualifiers_are_independent(self):
        z=dict(STATE='3',REASON='0',N='4000')
        f=dict(FILTER_STATE='3',FILTER_REASON='0',RAW_STATE='3',RAW_REASON='0',RAW_N='4000',OUT='0')
        self.assertTrue(host.qualification(z,f)['both_zero_qualifiers_pass'])
        f.update(RAW_STATE='4',RAW_REASON='2',OUT='10')
        q=host.qualification(z,f)
        self.assertTrue(q['median_zero_ready']); self.assertFalse(q['raw_zero_ready'])
        self.assertFalse(q['both_zero_qualifiers_pass']); self.assertFalse(q['motor_qualified'])
    def test_insufficient_or_failed_zero_not_qualified(self):
        f=dict(FILTER_STATE='3',FILTER_REASON='0',RAW_STATE='3',RAW_REASON='0',RAW_N='4000',OUT='0')
        for z in (dict(STATE='0',REASON='0',N='0'),dict(STATE='3',REASON='0',N='3999'),
                  dict(STATE='4',REASON='3',N='4000')):
            self.assertFalse(host.qualification(z,f)['both_zero_qualifiers_pass'])
    def test_no_motion_or_retry(self):
        c=host.ZeroConsole(None)
        for cmd in ('START','CLEAR','SWITCH START PWM','SWITCH START BRIDGE','BOOT B'):
            with self.assertRaises(ValueError): c.query(cmd)
        c.starts.add('ZERO SAMPLE')
        with self.assertRaises(ValueError): c.query('ZERO SAMPLE')
        with self.assertRaises(ValueError): c.command('FW END')

if __name__=='__main__': unittest.main()
