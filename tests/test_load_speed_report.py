from pathlib import Path
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
import report_load_speed as report


class ReportTests(unittest.TestCase):
    def test_recovery_requires_full_dwell_not_one_good_sample(self):
        rows=[]
        for k in range(300):
            rows.append(dict(time_s=5+k*.001,control_mode=3,
                             omega_true_rad_s=(240 if k<50 or k>=100 else 220)*3.141592653589793/30))
        self.assertAlmostEqual(report.settled_after(rows),100,places=6)

    def test_recovery_does_not_count_non_speed_mode_as_recovered(self):
        rows=[dict(time_s=5+k*.001,control_mode=0,omega_true_rad_s=240*3.141592653589793/30) for k in range(200)]
        self.assertIsNone(report.settled_after(rows))

    def test_smoke_real_logs_find_contact_tradeoff_and_no_contact_before_fixture(self):
        root=ROOT/'simulation/dob_simulink/load_speed_results/20261024_185121'
        if not root.exists():self.skipTest('Preserved smoke result unavailable')
        values=[]
        for enabled in (0,1):
            _,metric,checks=report.analyse(root/f'contact_early_seed001_enabled{enabled}.csv.gz')
            self.assertTrue(checks['no_early_contact'])
            self.assertTrue(checks['confirmed_after_contact'])
            values.append(metric)
        self.assertLess(values[1]['contact_entry_speed_rpm'],values[0]['contact_entry_speed_rpm'])
        self.assertGreater(values[1]['done_s'],values[0]['done_s'])


if __name__=='__main__':unittest.main()
