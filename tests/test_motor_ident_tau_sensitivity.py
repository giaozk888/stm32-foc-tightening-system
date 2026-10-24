import copy
from pathlib import Path
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from test_motor_identification import l_run
import motor_ident_tau_sensitivity as sensitivity


class TauSensitivityTests(unittest.TestCase):
    def test_known_response_minimum_stable_when_lowering_bound(self):
        run=l_run('LD');before=copy.deepcopy(run)
        out=sensitivity.search_run(run,.1,.3)
        self.assertEqual(len(out['searches']),9)
        for result in out['searches']:
            self.assertAlmostEqual(result['best_tau_us'],400.,delta=.01)
            self.assertAlmostEqual(result['unqualified_best_L_uH'],40.,delta=.001)
            self.assertEqual(result['boundary'],'INTERIOR')
        self.assertEqual(run,before)
        self.assertFalse(out['qualified'])

    def test_original_fault_guard_not_bypassed(self):
        run=l_run('LQ');run['fault']=1
        with self.assertRaises(sensitivity.admission.original.Insufficient):
            sensitivity.search_run(run,.1,.3)

    def test_cross_axis_failed_capture_not_silently_searched(self):
        run=l_run('LD')
        for row in run['rows']:row['iq']=.03
        out=sensitivity.search_run(run,.1,.3)
        self.assertEqual(out['searches'],[])
        self.assertIn('cross-axis',out['not_searched'])

    def test_real_capture_interior_minima_stable_but_not_qualified(self):
        path=Path(__file__).resolve().parents[1]/'tmp/motor-ident-voltage-batch-1792561436183568200.json'
        out=sensitivity.batch_search(path)
        for point,expected in zip(out['points'][:2],(20.03,11.18)):
            self.assertFalse(point['qualified'])
            latest=point['searches'][-1]
            self.assertEqual(latest['boundary'],'INTERIOR')
            self.assertAlmostEqual(latest['unqualified_best_L_uH'],expected,delta=.01)
            self.assertGreater(latest['prediction_rms_mA'],5.)
            self.assertLess(abs(latest['best_tau_us']-point['searches'][-3]['best_tau_us']),.001)
        self.assertTrue(all(not p.get('searches') for p in out['points'][2:]))
        self.assertFalse(out['automatic_parameter_write'])


if __name__=='__main__':unittest.main()
