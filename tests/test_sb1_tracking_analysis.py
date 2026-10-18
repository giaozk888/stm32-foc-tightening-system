"""Exact saved SB1 evidence only: no device imports or live operations."""
import contextlib
import io
from pathlib import Path
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
import analyze_sb1_tracking as audit


class TrackingAnalysisTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with contextlib.redirect_stdout(io.StringIO()): cls.result=audit.analyze()

    def test_full_rate_maximum_is_not_uart_peak(self):
        result=self.result
        self.assertAlmostEqual(result['speed_diagnostics']['speed_diag_max_rpm'],31.03975868,places=6)
        self.assertEqual(max(r['speed_rpm'] for r in result['uart_rows']),17.8)
        self.assertEqual(len(result['uart_rows']),32)

    def test_complete_tail_reproduces_existing_controller(self):
        result=self.result
        self.assertEqual(len(result['tail_rows']),32)
        self.assertEqual(result['startup_header']['total'],2015)
        self.assertEqual(result['startup_header']['fault_valid'],0)
        self.assertLess(result['tail_replay_max_error']['speed_iq_ref_A'],1e-6)
        self.assertLess(result['tail_replay_max_error']['lpf_rpm'],1e-5)
        self.assertGreaterEqual(result['tail']['dt_us_min'],990)
        self.assertLessEqual(result['tail']['dt_us_max'],1010)

    def test_no_claim_of_clean_current_or_full_speed_trace(self):
        result=self.result
        self.assertGreater(result['tail']['iq_error_rms_A'],.05)
        self.assertLess(abs(result['tail']['iq_error_mean_A']),.01)
        self.assertLess(result['tail_rows'][-1]['elapsed_us']-result['tail_rows'][0]['elapsed_us'],32000)
        self.assertEqual(result['hardware_operations'],0)
        self.assertFalse(result['controller_modified'])


if __name__=='__main__': unittest.main()
