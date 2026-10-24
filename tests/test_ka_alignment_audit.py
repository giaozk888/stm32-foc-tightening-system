import math
from pathlib import Path
import subprocess
import sys
import unittest
from test_torque_chain import ROOT
sys.path.insert(0,str(ROOT/'tools'))
import ka_alignment_audit as audit


class KaAlignmentAuditTests(unittest.TestCase):
    def test_known_positive_slope_and_intercept(self):
        r=audit.regression([0,100,-100,200,-200,50,-50,150],
            [.02,.03,.01,.04,0,.025,.015,.035],[.1]*8)
        self.assertAlmostEqual(r['ka'],.0001);self.assertAlmostEqual(r['b'],.02)
        self.assertAlmostEqual(r['r2'],1)

    def test_piecewise_filter_is_not_claimed_real_waveform_reconstruction(self):
        y=audit.held_current_filter([1]*8,[.1]*8)
        self.assertAlmostEqual(y[0],1-.2*(1-math.exp(-5)))
        self.assertGreater(y[-1],.99999)
        with self.assertRaises(ValueError):audit.held_current_filter([1],[0])

    def test_real_five_exact_evidence_common_lag_windows_and_no_automatic_selection(self):
        r=audit.audit(ROOT/'tmp/ka-repeat-batch-1792653173374577400.json')
        self.assertTrue(r['no_fixed_lag_positive_in_all_five'])
        self.assertEqual(r['approximate_lpf_positive_runs'],1)
        self.assertFalse(r['hardware_access']);self.assertFalse(r['parameter_writes'])
        for run in r['runs']:
            self.assertEqual(run['positive_measured_iq_windows'],run['moving_windows'])
            self.assertEqual(len({s['n'] for s in run['lag_sensitivity']}),1)
            self.assertEqual([s['lag_windows'] for s in run['lag_sensitivity']],[-2,-1,0,1,2])
            self.assertLess(run['primary_unshifted_post_startup']['ka'],0)
            self.assertFalse(run['exact_20ms_alignment_identifiable'])
            self.assertIsNone(run['auto_selected_delay']);self.assertIsNone(run['auto_selected_ka'])

    def test_cli_requires_only_existing_files_and_no_device_commands(self):
        p=subprocess.run([sys.executable,str(ROOT/'tools/ka_alignment_audit.py'),'--help'],capture_output=True,text=True)
        self.assertEqual(p.returncode,0);self.assertIn('FILES ONLY',p.stdout)
        source=(ROOT/'tools/ka_alignment_audit.py').read_text()
        for bad in ('import serial','open_port(','reset run','flash write','START\''):
            self.assertNotIn(bad,source)


if __name__=='__main__':unittest.main()
