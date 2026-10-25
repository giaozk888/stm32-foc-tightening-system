import copy
import sys
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'tools'))
import report_load_speed_contact as report


class ContactReportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        folder=ROOT/'simulation/dob_simulink/load_speed_contact_results/20261024_201508'
        cls.path=folder/'contact_cancel_seed001_candidate.csv.gz'
        if not cls.path.exists():raise unittest.SkipTest('Preserved Simulink smoke trace unavailable')
        cls.rows=report.read(cls.path)

    def test_real_cancel_trace_meets_boundary_contract(self):
        metrics,checks=report.analyse(self.rows,'candidate')
        self.assertEqual(metrics['cancel_events'],1)
        self.assertTrue(checks['contact_hold_no_target_increase'])
        self.assertTrue(checks['cancel_retains_slow'])

    def test_audit_detects_reintroduced_target_jump_and_current_overflow(self):
        rows=copy.deepcopy(self.rows)
        first=next(i for i,r in enumerate(rows) if r['contact_held'])
        rows[first]['selected_target_rpm']=240
        rows[first]['iq_cmd_a']=.501
        _,checks=report.analyse(rows,'candidate')
        self.assertFalse(checks['contact_hold_no_target_increase']);self.assertFalse(checks['iq_cap'])

    def test_audit_detects_retained_slow_in_torque_phase(self):
        rows=copy.deepcopy(self.rows);rows[-1]['fsm_state']=5;rows[-1]['schedule_slow']=1
        _,checks=report.analyse(rows,'candidate');self.assertFalse(checks['phase_scope'])


if __name__=='__main__':unittest.main()
