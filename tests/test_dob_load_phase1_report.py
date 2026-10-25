import csv
import gzip
import importlib.util
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('phase1_report', ROOT / 'tools/report_dob_load_phase1.py')
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)


class Phase1AuditTests(unittest.TestCase):
    def pair(self, folder, mutate=None):
        feature = ['load_state', 'load_label_valid', 'load_coverage', 'load_accepted',
                   'load_feature_updated', 'load_reason', 'load_quality_resets',
                   'load_mean_a', 'load_trend_a_s', 'load_dwell_ms', 'load_source_age_ms']
        columns = audit.CONTROL + feature
        a, b = [], []
        for k in range(2):
            row = dict.fromkeys(columns, 0)
            row.update(time_s=k*.001, dob_valid=1, lpf_updated=1)
            a.append(row.copy())
            row.update(load_state=1, load_label_valid=int(k == 0), load_coverage=.9,
                       load_accepted=1, load_reason=0 if k == 0 else 5,
                       load_mean_a=.01, load_dwell_ms=100)
            b.append(row)
        if mutate:
            mutate(b)
        files = [Path(folder) / 'off.csv.gz', Path(folder) / 'on.csv.gz']
        for file, rows in zip(files, (a, b)):
            with gzip.open(file, 'wt', newline='') as f:
                w = csv.DictWriter(f, columns)
                w.writeheader()
                w.writerows(rows)
        return files

    def test_classification_can_change_without_touching_control(self):
        with tempfile.TemporaryDirectory() as folder:
            result = audit.audit_pair(*self.pair(folder))
            self.assertEqual(result['rows'], 2)
            self.assertEqual(result['rejected_frames_checked'], 1)

    def test_detects_control_change(self):
        with tempfile.TemporaryDirectory() as folder:
            files = self.pair(folder, lambda b: b[1].update(iq_cmd_a=.01))
            with self.assertRaisesRegex(AssertionError, 'Control/truth/input changed'):
                audit.audit_pair(*files)

    def test_detects_rejected_sample_pollution(self):
        with tempfile.TemporaryDirectory() as folder:
            files = self.pair(folder, lambda b: b[1].update(load_mean_a=.7))
            with self.assertRaisesRegex(AssertionError, 'polluted'):
                audit.audit_pair(*files)

    def test_detects_rejected_valid_credit(self):
        with tempfile.TemporaryDirectory() as folder:
            files = self.pair(folder, lambda b: b[1].update(load_accepted=2))
            with self.assertRaisesRegex(AssertionError, 'credited'):
                audit.audit_pair(*files)


if __name__ == '__main__':
    unittest.main()
