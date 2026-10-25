import csv
import gzip
import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
spec = importlib.util.spec_from_file_location('repair_report', ROOT / 'tools/report_dob_load_repair.py')
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)


class RepairAuditTests(unittest.TestCase):
    def files(self, folder, mutate=None):
        fields = audit.CONTROL + audit.FEATURES + ['load_trend_state', 'load_trend_valid',
            'load_trend_filtered_a_s', 'load_trend_dwell_ms']
        historical, before, after = [], [], []
        for k in range(2):
            r = dict.fromkeys(fields, 0)
            r.update(time_s=3.799+k*.001, dob_valid=1, lpf_updated=1, warmup_s=2,
                     load_state=4, load_label_valid=1, load_accepted=1, load_mean_a=.03,
                     load_dwell_ms=100, load_trend_state=2, load_trend_valid=1)
            historical.append(r.copy())
            r.update({'legacy_' + name: r[name] for name in audit.FEATURES})
            before.append(r.copy())
            if k:
                r.update(dob_valid=0, lpf_updated=0, dob_status=4096, load_label_valid=0,
                         load_trend_valid=0, load_reason=5)
            after.append(r)
        if mutate:
            mutate(after)
        paths = [Path(folder) / 'short_gap_revision0.csv.gz',
                 Path(folder) / 'short_gap_revision1.csv.gz', Path(folder) / 'original.csv.gz']
        for path, rows in zip(paths, (before, after, historical)):
            with gzip.open(path, 'wt', newline='') as f:
                w = csv.DictWriter(f, list(rows[0]))
                w.writeheader()
                w.writerows(rows)
        return paths

    def test_recovery_hold_can_change_status_but_not_control_or_filter(self):
        with tempfile.TemporaryDirectory() as folder:
            r = audit.audit_pair(*self.files(folder))
            self.assertEqual(r['held_missing_epochs'], 1)

    def test_detects_fake_warmup_credit(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaisesRegex(AssertionError, 'advanced'):
                audit.audit_pair(*self.files(folder, lambda a: a[1].update(warmup_s=2.003)))

    def test_detects_actuator_change(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaisesRegex(AssertionError, 'Control/truth'):
                audit.audit_pair(*self.files(folder, lambda a: a[1].update(iq_cmd_a=.1)))

    def test_detects_rejected_trend_update(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaisesRegex(AssertionError, 'feature/timer'):
                audit.audit_pair(*self.files(folder, lambda a: a[1].update(load_trend_filtered_a_s=.7)))


if __name__ == '__main__':
    unittest.main()
