from pathlib import Path
import sys
import unittest
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import feedback_safety_replay as replay

class SavedFeedbackTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): replay.compile_kernel()

    def test_actual_pipeline_constant_alignment_and_no_motor_qualification(self):
        row = replay.replay([[1600, 1600]]*100, (1600, 1600))
        self.assertEqual((row['consumed'], row['trip_seq'], row['repaired']), (97, 0, 0))
        self.assertFalse(row['motor_qualified'])
        self.assertFalse(row['acquisition_timing_verified'])

    def test_single_repair_and_persistent_current_shutdown(self):
        samples = [[1600, 1600] for _ in range(20)]
        samples[5] = [0, 1600]
        row = replay.replay(samples, (1600, 1600))
        self.assertEqual((row['trip_seq'], row['repaired']), (0, 1))
        samples[10:] = [[500, 1600]]*10
        row = replay.replay(samples, (1600, 1600))
        self.assertEqual(row['reason'], 10)  # Confirmed FILTERED current.
        self.assertGreater(row['trip_seq'], 0)
        self.assertLess(row['consumed'], len(samples)-3)

    def test_repair_budget_failure_never_restarts(self):
        samples = [[1600, 1600] for _ in range(80)]
        for i in (2, 5, 8, 11): samples[i] = [0, 1600]
        row = replay.replay(samples, (1600, 1600))
        self.assertEqual((row['reason'], row['repaired'], row['trip_seq']), (9, 4, 13))
        self.assertEqual(row['input_pairs'], 80)

    def test_malformed_data_rejected(self):
        for samples in ([[0, 0]]*3, [[True, 0]]*4, [[4096, 0]]*4,
                        [[0.5, 0]]*4, [[0, 0, 0]]*4):
            with self.assertRaises(ValueError): replay.replay(samples, (0, 0))

    def test_saved_captures_are_replay_only_not_a_bridge_pass(self):
        folder = ROOT / 'safety_backups/switch-trend-compare-20261013'
        for name in ('off-1791879204193467700.json', 'pwm-1791880594613936800.json'):
            row = replay.saved_capture(folder / name)
            self.assertEqual(row['input_pairs'], 3600)
            self.assertFalse(row['motor_qualified'])
            self.assertTrue(row['historical'])
            if name.startswith('off-'):
                self.assertEqual((row['consumed'], row['trip_seq'], row['repaired']), (3597, 0, 37))
            else:
                self.assertEqual((row['trip_seq'], row['reason']), (1158, 9))
                self.assertGreater(row['window_repairs'], 3)

if __name__ == '__main__': unittest.main()
