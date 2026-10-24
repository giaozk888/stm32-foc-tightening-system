"""Measured current samples may be rejected, but time/voltage cannot vanish."""
import copy
import json
from pathlib import Path
import sys
import unittest
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
from test_motor_identification import l_run
import motor_ident_valid_sample_report as report
import motor_identification_report as original


class ValidSampleTests(unittest.TestCase):
    def test_clean_transient_not_filtered_and_original_tau_recovered(self):
        for mode in ('LD','LQ'):
            r=l_run(mode);before=copy.deepcopy(r)
            out=report.fit_observations(r,.1)
            self.assertEqual(out['accepted_current_samples'],32)
            self.assertEqual(out['rejected_current_samples'],0)
            self.assertLess(abs(out['inductance_h']-40e-6),1e-6)
            self.assertFalse(out['current_replacement']);self.assertFalse(out['time_compression'])
            self.assertEqual(r,before)

    def test_isolated_spike_excluded_but_its_voltage_history_is_used(self):
        r=l_run('LD');r['rows'][18]['id']+=.08;before=copy.deepcopy(r)
        out=report.fit_observations(r,.1)
        self.assertEqual(out['rejected_current_samples'],1)
        self.assertEqual(out['rejected'][0]['seq'],r['rows'][18]['seq'])
        self.assertEqual(out['accepted_current_samples'],31)
        self.assertLess(abs(out['inductance_h']-40e-6),1e-6)
        rows,keep,reject=report.select_samples(r)
        intervals,excluded=report.available_intervals(rows,keep)
        bridge=next(x for x in intervals if x[0]==17 and x[1]==19)
        self.assertEqual(len(bridge[2]),2)
        self.assertAlmostEqual(sum(p[-1] for p in bridge[2]),.0001)
        self.assertEqual(r,before)

    def test_actual_missing_frame_excludes_affected_intervals_not_entire_run(self):
        r=l_run('LD');r['rows'].pop(12)
        with self.assertRaises(original.Insufficient):original.fit_l(r,.1)
        out=report.fit_observations(r,.1)
        self.assertTrue(out['excluded_intervals'])
        self.assertTrue(all(x['reason']=='MISSING_RECORDED_VOLTAGE_OR_TIME' for x in out['excluded_intervals']))
        self.assertLess(abs(out['inductance_h']-40e-6),1e-6)
        self.assertNotEqual(out['accepted_us'][12]-out['accepted_us'][11],50)

    def test_fault_or_unverified_timing_never_promoted_by_filtering(self):
        r=l_run('LQ');r['fault']=1
        with self.assertRaises(original.Insufficient):report.fit_observations(r,.1)
        r=l_run('LQ');r['latch_evidence']={'verified':False}
        out=report.fit_observations(r,.1)
        self.assertIsNone(out['inductance_h']);self.assertIn('TIMING_UNQUALIFIED',out['quality_error'])
        out=report.fit_observations(r,.1,fraction=.3)
        self.assertIsNone(out['inductance_h']);self.assertIn('MODEL_ONLY',out['quality_error'])
        self.assertFalse(r['latch_evidence']['verified'])

    def test_actual_voltage_batch_binary_provenance_and_counts(self):
        path=ROOT/'tmp/motor-ident-voltage-batch-1792561436183568200.json'
        before=path.read_bytes();out=report.batch_report(path,fraction=.5005)
        self.assertEqual([p.get('accepted_current_samples') for p in out['points']],[31,29,30,None])
        self.assertEqual([p.get('rejected_current_samples') for p in out['points']],[1,3,2,None])
        self.assertTrue(all(p.get('inductance_h') is None for p in out['points']))
        self.assertIsNone(out['ld']);self.assertIsNone(out['lq']);self.assertFalse(out['automatic_pi_write'])
        self.assertEqual(path.read_bytes(),before)


if __name__=='__main__':unittest.main()
