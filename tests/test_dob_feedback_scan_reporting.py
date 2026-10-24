"""Reporting-only regressions; no MATLAB/hardware/native artifacts needed."""
import importlib.util
import math
from pathlib import Path
import unittest

P=Path(__file__).resolve().parents[1]/'tools/report_dob_feedback_scan.py'
S=importlib.util.spec_from_file_location('feedback_report',P)
report=importlib.util.module_from_spec(S);S.loader.exec_module(report)


def fixture():
    rows=[]
    for hyp in ['measurement','torque']:
        for seed in range(1,101):
            common=dict(case_name=hyp,seed=seed,feedback_gate_pass=1,guard_faults=0,
                        cap_obeyed=1,total_limit_obeyed=1,finite=1)
            common.update({key:1.0 for key in report.METRICS})
            rows.append(dict(common,gain=0,cap_a=.025))
            for gain in [.15,.25,.5]:
                for cap in [.00625,.0125,.025]:
                    r=dict(common,gain=gain,cap_a=cap)
                    r['true_load_speed_mae_rpm']=(.8 if gain==.25 else .9) if seed<=60 else (.5 if gain==.5 else .95)
                    rows.append(r)
    return rows


class ReportingTests(unittest.TestCase):
    def test_selection_does_not_tune_on_holdout(self):
        c=report.select_tuning_candidate(fixture())['selected']
        self.assertEqual((c['gain'],c['cap_a']),(.25,.00625))

    def test_failed_trial_disqualifies_candidate_not_deleted(self):
        rows=fixture()
        for r in rows:
            if r['gain']==.25 and r['seed']==1:
                r['feedback_gate_pass']=0
        c=report.select_tuning_candidate(rows)['selected']
        self.assertNotEqual(c['gain'],.25)
        self.assertEqual(len(rows),2000)

    def test_all_split_and_event_counts(self):
        out=report.summarize(fixture())
        self.assertEqual(len(out),2*3*3*9*len(report.METRICS))
        q=next(x for x in out if x['split']=='heldout' and x['event']=='step')
        self.assertEqual((q['n'],q['finite_pairs'],q['missing_pairs']),(20,20,0))

    def test_missing_recovery_reported_not_zero_filled(self):
        base={('measurement',1):{'speed_recovery_s':1.0},('measurement',2):{'speed_recovery_s':1.0}}
        rows=[dict(case_name='measurement',seed=1,speed_recovery_s=math.nan),
              dict(case_name='measurement',seed=2,speed_recovery_s=.8)]
        s=report.pair_stats(rows,base,'speed_recovery_s')
        self.assertEqual((s['n'],s['finite_pairs'],s['missing_pairs']),(2,1,1))
        self.assertAlmostEqual(s['on_mean'],.8)


if __name__=='__main__':unittest.main()
