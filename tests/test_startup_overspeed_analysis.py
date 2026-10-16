"""No hardware access: arithmetic and hypothetical-model regression only."""
import json
import unittest
import analyze_startup_overspeed as analysis


class OverspeedAnalysisTests(unittest.TestCase):
    def test_angle_wrap(self):
        self.assertEqual(analysis.delta14(1, 16383), 2)
        self.assertEqual(analysis.delta14(16383, 1), -2)

    def test_captured_units_and_velocity_reconstruction(self):
        receipt = json.loads(analysis.RECEIPT.read_text('utf-8'))
        result = analysis.analyze(receipt)
        self.assertEqual(result['first_flags'], 1024)
        self.assertEqual(result['frame_count'], 28)
        self.assertEqual(result['first_fault_us'], 27853)
        self.assertLess(result['adjacent_instant_max_discrepancy_rpm'], .101)
        self.assertTrue(result['lpf_all_intervals_consistent_with_truncated_format'])
        self.assertTrue(result['all_early_id_positive_vd_negative'])
        self.assertTrue(result['all_early_iq_negative_vq_positive'])

    def test_missing_frame_not_silently_accepted(self):
        receipt = json.loads(analysis.RECEIPT.read_text('utf-8'))
        receipt['startup_frames'].pop()
        with self.assertRaises(ValueError):
            analysis.analyze(receipt)

    def test_delay_alone_and_inverted_measurement_hypotheses(self):
        for delay in (1, 2, 3):
            normal = analysis.hypothetical_rl(1, delay)
            inverted = analysis.hypothetical_rl(-1, delay)
            self.assertLess(normal['peak_current_A'], .01)
            self.assertEqual(normal['saturated_steps'], 0)
            self.assertGreater(inverted['peak_current_A'], 1.)
            self.assertGreater(inverted['saturated_steps'], 0)


if __name__ == '__main__':
    unittest.main()
