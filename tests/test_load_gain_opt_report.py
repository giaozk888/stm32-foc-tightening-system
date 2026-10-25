from pathlib import Path
import sys
import unittest
import pandas as pd

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'tools'))
import report_load_gain_opt as report
from prepare_load_gain_opt import PROFILES


class OptAuditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        root=ROOT/'simulation/dob_simulink/load_gain_results/20261024_212550'
        cls.rows=pd.read_csv(root/'step_seed001_adaptive.csv.gz')
        cls.quiet=pd.read_csv(root/'no_load_seed001_adaptive.csv.gz')

    def test_reference_is_valid_original_profile_and_fast_upper_bound(self):
        for profile in ('adaptive','fast'):
            _,checks=report.analyse(self.rows,'step',profile,PROFILES)
            self.assertTrue(all(checks.values()),[k for k,v in checks.items() if not v])

    def test_floor_rule_detects_missing_nonzero_floor(self):
        _,checks=report.analyse(self.quiet,'no_load','floor',PROFILES)
        self.assertFalse(checks['qualified_unloaded_request_equals_floor'])

    def test_gain_rate_ceiling_stays_profile_specific(self):
        f=self.rows.copy();index=int(f.index[(f.gain_active==1)&(f.gain_selected>0)][5])
        f.loc[index,'gain_selected']=f.loc[index-1,'gain_selected']+.006
        _,checks=report.analyse(f,'step','fast',PROFILES)
        self.assertFalse(checks['gain_slew'])


if __name__=='__main__':unittest.main()
