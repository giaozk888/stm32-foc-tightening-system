from pathlib import Path
import sys
import unittest
import numpy as np
import pandas as pd

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'tools'))
import report_load_gain as report


class GainAuditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        p=ROOT/'simulation/dob_simulink/load_gain_results/20261024_212049'
        if not p.exists():raise unittest.SkipTest('Preserved software smoke trace unavailable')
        cls.adaptive=pd.read_csv(p/'unload_seed001_adaptive.csv.gz')
        cls.fixed=pd.read_csv(p/'contact_early_seed001_fixed.csv.gz')

    def test_preserved_trace_passes_implementation_checks(self):
        _,checks=report.analyse(self.adaptive,'unload','adaptive')
        self.assertTrue(all(checks.values()),[k for k,v in checks.items() if not v])

    def test_out_of_range_gain_and_unclamped_sum_are_detected(self):
        f=self.adaptive.copy();k=int(np.flatnonzero(f.fsm_state==3)[-1])
        f.loc[k,'gain_selected']=.30;f.loc[k,'iq_cmd_a']=.501
        _,checks=report.analyse(f,'unload','adaptive')
        self.assertFalse(checks['gain_bounds']);self.assertFalse(checks['iq_cap']);self.assertFalse(checks['total_clamp'])

    def test_illegal_saturated_refresh_and_expired_compensation_are_detected(self):
        f=self.fixed.copy();sat=(f.dob_status.to_numpy().astype(np.int64)&128)!=0
        k=int(np.flatnonzero(sat)[0]+1);f.loc[k,'feedback_state']=2
        _,checks=report.analyse(f,'contact_early','fixed');self.assertFalse(checks['saturated_source_cannot_track'])
        f=self.fixed.copy();f.loc[k,'feedback_state']=5;f.loc[k,'iq_dob_a']=.001
        _,checks=report.analyse(f,'contact_early','fixed');self.assertFalse(checks['original_hold_fade_expiry_clock'])


if __name__=='__main__':unittest.main()
