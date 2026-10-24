"""Saved SC1 evidence only; never opens hardware or modifies receipts."""
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
import scurve_fsm_report as report

class ScurveReportTests(unittest.TestCase):
    def test_same_session_snapshot_and_equal_window_comparison(self):
        r=report.report(ROOT/'tmp/scurve-fsm-run-1792478491388804100.json')
        self.assertFalse(r['hardware_access'])
        self.assertEqual(r['timing']['deadline_miss'],0)
        self.assertEqual(r['timing']['actual_late_count'],0)
        self.assertEqual(r['cur_confirm']['fault'],0)
        for name in ('AW0','L00','SC1'): self.assertEqual(r['comparisons'][name]['count'],95)
        self.assertAlmostEqual(r['comparisons']['SC1']['mean_rpm'],233.11578947)
        self.assertLess(r['comparisons']['SC1']['mean_rpm'],r['comparisons']['AW0']['mean_rpm'])
        self.assertEqual(r['terminal']['OUTCOME'],'RUNDOWN_TIMEOUT')
        self.assertIn('NOT_MEASURED',r['reference_ramp_capture'])
        self.assertEqual(len(r['startup_trace']['rows']),32)
        self.assertEqual(r['startup_trace']['schema'],1)
        self.assertEqual(r['startup_trace']['total'],8000)

    def test_wrong_identity_is_rejected_not_decoded(self):
        with patch.object(report,'BIN_SHA','0'*64):
            with self.assertRaisesRegex(ValueError,'identity required'):
                report.report(ROOT/'tmp/scurve-fsm-run-1792478491388804100.json')

    def test_active_or_wrong_trace_schema_is_rejected(self):
        with self.assertRaisesRegex(ValueError,'schema-1'):
            report.trace_v1(bytes(0x20000),{'cl_startup':(0x20000000,4310)})
        with self.assertRaisesRegex(ValueError,'frozen rolling tail'):
            report.trace_v1(bytes(0x20000),{'cl_startup':(0x20000000,2000)})

    def test_raw_receipts_remain_authoritative(self):
        receipt=ROOT/'tmp/scurve-fsm-run-1792478491388804100.json'
        before=receipt.read_bytes(); r=json.loads(before)
        report.report(receipt)
        self.assertEqual(receipt.read_bytes(),before)
        self.assertFalse(r['pass_'])
        self.assertTrue(r['preflight_pass'])
        self.assertEqual(r['start_attempts'],1)

if __name__=='__main__': unittest.main()
