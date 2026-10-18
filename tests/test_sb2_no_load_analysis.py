"""File-only checks on the retained SB2 diagnosis and stopped-frame selection."""
import contextlib
import io
from pathlib import Path
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
import analyze_sb2_no_load as audit


class NoLoadAnalysisTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with contextlib.redirect_stdout(io.StringIO()): cls.report=audit.main()

    def test_exact_full_cycle_evidence_not_claimed_speed_pass(self):
        full=self.report['full']
        self.assertTrue(full['full_cycle'])
        self.assertLess(full['speed_interval']['speed_diag_max_rpm'],2)
        self.assertEqual(full['board_snapshot']['first_fault']['valid'],0)

    def test_zero_demand_stop_rows_are_excluded(self):
        full=self.report['full']; tail=full['active_tail']
        self.assertEqual(len(full['tail_rows']),32)
        self.assertEqual(tail['frames'],29)
        self.assertAlmostEqual(tail['means']['iq_ref_A'],.15,places=6)
        self.assertAlmostEqual(tail['means']['iq_A'],.0496090268,places=6)
        self.assertAlmostEqual(tail['iq_error_mean_A'],.1003909792,places=6)

    def test_voltage_saturation_is_not_misreported_as_integrator_clamp(self):
        tail=self.report['full']['active_tail']
        self.assertEqual(tail['at_0p8V_limit_frames'],17)
        self.assertEqual(tail['above_99pct_limit_frames'],29)
        self.assertLess(tail['max_abs_integrator_V']['current_int_q_V'],.75)
        self.assertLess(tail['pi_output_residual_max_V'],1e-6)

    def test_timing_still_passes_but_short_pretransition_tail_is_only_two_rows(self):
        timing=self.report['full']['board_snapshot']['timing']
        self.assertEqual(timing['deadline_miss'],0)
        self.assertEqual(timing['actual_late_count'],0)
        self.assertLess(timing['wall_max_us'],30)
        self.assertEqual(self.report['short']['active_tail']['frames'],2)


if __name__=='__main__': unittest.main()
