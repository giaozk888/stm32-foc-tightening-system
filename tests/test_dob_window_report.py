from pathlib import Path
import sys
import unittest
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
from report_dob_window_scan import metrics,eligibility
from report_dob_trend_scan import match_events
class ReportTests(unittest.TestCase):
    def test_matching_does_not_reward_early_or_duplicate_detection(self):
        r=match_events([2.9,3.1,3.2],[3.0],.8)
        self.assertEqual((r['hits'],r['false'],r['misses']),(1,2,0))
        self.assertAlmostEqual(r['delays'][0],.1)
    def test_more_false_events_or_switching_disqualifies_short_window(self):
        rows=[]
        for split,seed in [('train',1),('heldout',61)]:
            for w in (100,50):
                rows.append(dict(scenario='real_measurement',seed=seed,split=split,window_ms=w,
                    false_events=0 if w==100 else 1,missed_events=0,trend_valid_rate=.95,
                    trend_changes=10 if w==100 else 20,level_changes=2,matched_delay_ms=150 if w==100 else 100))
        r=eligibility(rows,50,'heldout')
        self.assertFalse(r['eligible']);self.assertIn('real_measurement_no_extra_fp',r['failed'])
        self.assertIn('real_measurement_trend_changes_bound',r['failed'])
    def test_missing_detection_remains_missing_not_zero_delay(self):
        rows=[]
        for k in range(7001):
            t=k*.001;row=dict(time_s=t,load_ground_truth_a=.04 if 3<=t<4.6 else 0)
            row.update({'w100_'+key:value for key,value in dict(trend=1,trend_valid=1,
                level=1,level_valid=1,resets=0,level_changes=1,trend_changes=1).items()});rows.append(row)
        m=dict(eval_s=[2.3,6.9],event_s=3.,unload_s=4.6,event_match_max_s=.8)
        r=metrics(rows,m,dict(scenario='unload',seed=1),100)
        self.assertEqual(r['missed_events'],2);self.assertIsNone(r['matched_delay_ms'])
if __name__=='__main__':unittest.main()
