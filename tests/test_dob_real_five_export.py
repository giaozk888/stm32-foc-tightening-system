"""Files-only real capture export and simulation contract checks."""
import csv
import hashlib
import importlib.util
import json
from pathlib import Path
import unittest
ROOT=Path(__file__).resolve().parents[1]
ENV=ROOT/'simulation/dob_simulink/real_five'

class RealFiveExportTests(unittest.TestCase):
    def test_five_actual_windows_and_hashes(self):
        m=json.loads((ENV/'data/manifest.json').read_text())
        self.assertEqual(m['independent_motor_runs'],5);self.assertEqual(m['samples'],960)
        self.assertFalse(m['load_ground_truth_available']);self.assertFalse(m['full_historical_replay'])
        self.assertEqual(hashlib.sha256((ENV/'data/events.csv').read_bytes()).hexdigest(),m['events_sha256'])
        for s in m['sources']:
            self.assertEqual(hashlib.sha256(Path(s['receipt']).read_bytes()).hexdigest(),s['receipt_sha256'])
            self.assertEqual(hashlib.sha256(Path(s['csv']).read_bytes()).hexdigest(),s['csv_sha256'])
    def test_export_preserves_raw_spike_and_holdout_split_has_no_source_overlap(self):
        with (ENV/'data/events.csv').open(newline='') as f:r=list(csv.DictReader(f))
        self.assertGreater(max(float(x['iq_raw_a']) for x in r),1.37)
        self.assertLess(min(float(x['iq_raw_a']) for x in r),-.48)
        for sid in range(1,6):self.assertEqual(sum(int(x['source_id'])==sid for x in r),192)
        source=(ENV/'real_five_inputs.m').read_text()
        self.assertIn('seed<=60,pool=1:3;else,pool=4:5;',source)
        self.assertNotIn('dob_estimate_a',source)
    def test_strict_full_gate_requires_delay_recovery_and_keeps_independent_limits(self):
        source=(ENV/'run_real_five_scan.m').read_text()
        self.assertIn('m.detection_delay_s<=c.accept.delay_s&&m.estimate_recovery_s<=c.accept.recovery_s',source)
        self.assertIn('ON SKIPPED',source)
        self.assertIn("input_hash(T),baselines(key(hypothesis,seed))",source)
        native=(ROOT/'simulation/dob_simulink/native/dob_host.c').read_text()
        self.assertIn('cap_a=fminf(.025f',native)
        case=(ENV/'real_five_run_case.m').read_text()
        self.assertIn('abs(T.iq_cmd_a)<=.5+1e-7',case)
        self.assertIn('abs(T.iq_dob_a)<=cap+1e-7',case)

if __name__=='__main__':unittest.main()
