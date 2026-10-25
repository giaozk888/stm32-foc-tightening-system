import importlib.util
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
spec = importlib.util.spec_from_file_location('trend_scan', ROOT / 'tools/report_dob_trend_scan.py')
scan = importlib.util.module_from_spec(spec)
spec.loader.exec_module(scan)


class TrendScanTests(unittest.TestCase):
    def test_early_and_duplicate_activations_are_not_free_detections(self):
        r = scan.match_events([2.9, 3.1, 3.2, 4.0], [3.0], .8)
        self.assertEqual((r['hits'], r['false'], r['misses']), (1, 3, 0))
        self.assertAlmostEqual(r['delays'][0], .1)

    def test_late_or_missing_event_is_not_zero_delay(self):
        r = scan.match_events([3.9], [3.0], .8)
        self.assertEqual((r['hits'], r['false'], r['misses']), (0, 1, 1))
        self.assertEqual(r['delays'], [])

    def test_quality_gap_does_not_invent_a_new_onset(self):
        result = scan.episode_onsets([2.29, 2.3, 2.31, 2.32, 2.33, 2.34],
                                    [2, 2, 2, 2, 1, 2], [1, 1, 0, 1, 1, 1], 2, 2.3, 6.9)
        self.assertEqual(result, [2.3, 2.34])

    def test_active_episode_is_not_hidden_by_invalid_first_window_frame(self):
        result = scan.episode_onsets([2.29, 2.3, 2.31, 2.32],
                                    [2, 2, 2, 2], [1, 0, 0, 1], 2, 2.3, 6.9)
        self.assertEqual(result, [2.32])

    def test_high_clear_requires_fresh_evidence(self):
        d = scan.high_clear_delay([4.59, 4.6, 4.61, 4.62], [4, 4, 2, 2], [1, 1, 0, 1], 4.6)
        self.assertAlmostEqual(d, .02)

    def test_no_heldout_data_cannot_pass_validation(self):
        cfg = {'classification': {'scenarios': ['step']},
               'scan': {'accept': {'real_transition_ratio_max': 1.25}}}
        r = scan.eligibility([], 'base', 'base', cfg, 'heldout')
        self.assertFalse(r['eligible'])

    def test_low_delay_cannot_hide_extra_false_events(self):
        cfg = {'classification': {'scenarios': ['step']},
               'scan': {'accept': {'real_transition_ratio_max': 1.25}}}
        rows = [dict(scenario='step', profile=name, split='train', false_events=fp,
                     missed_events=0, trend_valid_rate=1, rise_delay_s=delay, fall_delay_s=delay)
                for name, fp, delay in [('base', 0, .13), ('fast', 1, .07)]]
        self.assertTrue(scan.eligibility(rows, 'base', 'base', cfg, 'train')['eligible'])
        self.assertFalse(scan.eligibility(rows, 'fast', 'base', cfg, 'train')['eligible'])


if __name__ == '__main__':
    unittest.main()
