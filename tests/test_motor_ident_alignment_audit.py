"""Offline alignment model checks; no fabricated latch proof or hardware IO."""
import copy
import sys
import unittest
from pathlib import Path
from test_motor_identification import l_run
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
import motor_ident_alignment_audit as audit


class AlignmentAuditTests(unittest.TestCase):
    def test_known_analytic_rl_residual_and_no_inductance_output(self):
        for mode in ('LD','LQ'):
            rows=l_run(mode)['rows']
            before=copy.deepcopy(rows)
            out=audit.ideal_rl_residual(rows,mode,rs=.1,fraction=.3)
            self.assertLess(out['minimum_prediction_rms_a'],.0001)
            self.assertFalse(out['exceeds_original_rms_gate'])
            self.assertFalse(out['boundary_minimum'])
            self.assertIsNone(out['inductance_h'])
            self.assertEqual(rows,before)

    def test_missing_rows_not_interpolated(self):
        rows=l_run('LD')['rows'];rows[8]['seq']+=1
        self.assertEqual(audit.ideal_rl_residual(rows,'LD')['status'],
            'NOT_EVALUATED_MISSING_INTERVAL_VOLTAGE')

    def test_actual_captures_hash_checked_and_all_results_unqualified(self):
        out=audit.audit(ROOT/'tmp/motor-ident-l-repeat-batch-1792559788606362800.json')
        self.assertIsNone(out['ld']);self.assertIsNone(out['lq'])
        self.assertFalse(out['firmware_changed']);self.assertFalse(out['hardware_access'])
        points=out['points'];self.assertEqual(len(points),6)
        continuous=[p for p in points if not p['seq_gaps']]
        self.assertEqual(len(continuous),4)
        for p in continuous:
            self.assertEqual(p['pending_source_mismatches'],0)
            self.assertTrue(p['clock_certified'])
            self.assertFalse(p['lite_probe']['detailed_points_captured'])
            for h in p['hypothesis']:
                self.assertTrue(h['exceeds_original_rms_gate'])
                self.assertIsNone(h['inductance_h'])


if __name__=='__main__':unittest.main()
