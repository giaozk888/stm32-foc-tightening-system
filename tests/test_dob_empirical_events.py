"""Real-event provenance/shape checks, no board transport imports/actions."""
import csv
import hashlib
import importlib.util
import json
from pathlib import Path
import statistics
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
ENV = ROOT / 'simulation/dob_simulink/empirical'


class EmpiricalEventsTests(unittest.TestCase):
    def test_frozen_sources_and_dense_csv_hash(self):
        m = json.loads((ENV/'data/manifest.json').read_text())
        self.assertEqual(hashlib.sha256((ENV/'data/events.csv').read_bytes()).hexdigest(), m['events_sha256'])
        self.assertFalse(m['occurrence_rate_identified'])
        self.assertFalse(m['current_spikes_proven_noise_only'])
        self.assertFalse(m['load_ground_truth_available'])
        for s in m['sources']:
            self.assertEqual(s['dense_samples'], 40)
            self.assertEqual(s['sparse_samples_excluded'], 32)
            for field in ['receipt', 'elf']:
                self.assertEqual(hashlib.sha256(Path(s[field]).read_bytes()).hexdigest(), s[field+'_sha256'])

    def test_only_dense_paired_events_and_explicit_residual(self):
        with (ENV/'data/events.csv').open(newline='') as f:
            rows = list(csv.DictReader(f))
        self.assertEqual(len(rows), 80)
        for sid in ['1', '2']:
            block = [r for r in rows if r['source_id'] == sid]
            times = [int(r['original_us']) for r in block]
            self.assertTrue(all(900 <= b-a <= 1100 for a, b in zip(times, times[1:])))
            iq = [float(r['iq_raw_a']) for r in block]
            for i, r in enumerate(block):
                center = statistics.median(iq[max(0,i-2):min(40,i+3)])
                self.assertAlmostEqual(float(r['iq_residual_a']), iq[i]-center)
        extreme = min(rows, key=lambda r: float(r['id_raw_a']))
        self.assertLess(float(extreme['id_raw_a']), -.69)
        self.assertLess(float(extreme['iq_raw_a']), -.77)

    def test_verified_export_is_reproducible(self):
        spec = importlib.util.spec_from_file_location('empirical_export', ENV/'export_events.py')
        exporter = importlib.util.module_from_spec(spec); spec.loader.exec_module(exporter)
        with tempfile.TemporaryDirectory() as folder:
            m = exporter.export(folder)
            self.assertEqual(m['events_sha256'], json.loads((ENV/'data/manifest.json').read_text())['events_sha256'])


if __name__ == '__main__':
    unittest.main()
