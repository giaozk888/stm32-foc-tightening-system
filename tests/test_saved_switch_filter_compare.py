"""Same-data real-C replay, not new acquisition or bridge qualification."""
import json
import subprocess
import sys
import unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'tools'))
import saved_switch_filter_compare as replay

class SavedSwitchFilterCompareTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.result = replay.compare()

    def test_saved_capture_same_center_indices(self):
        r = self.result
        self.assertEqual(r['source_sha256'], 'df4d7aa3733370b13520cd310c773250b4195fceb46e1071fbdeb3f600f5ee0c')
        self.assertEqual(r['source_pairs'], 3600)
        for name in ('raw', 'median3', 'trend4'):
            self.assertEqual(r[name]['pairs'], 3597)
        self.assertEqual(r['raw']['outside100'], 17)
        self.assertEqual(r['raw']['hit4A'], [0, 0, 1])
        self.assertEqual(r['median3']['changed_pairs'], 2379)
        self.assertEqual(r['trend4']['changed_pairs'], 35)
        for name in ('median3', 'trend4'):
            self.assertEqual(r[name]['outside100'], 0)
            self.assertEqual(r[name]['hit4A'], [0, 0, 0])
        self.assertTrue(r['replay_only'])
        self.assertFalse(r['new_acquisition'])
        self.assertFalse(r['bridge_switch_test'])
        self.assertFalse(r['motor_qualified'])

    def run_pairs(self, pairs):
        p = subprocess.run([str(replay.EXE)], input=''.join(f'{u} {v}\n' for u,v in pairs),
                           text=True, capture_output=True, check=True)
        return json.loads(p.stdout)

    def test_isolated_center_repair_and_linear_ramp_preserved(self):
        pairs = [(1560,1560)]*10
        pairs[4] = (2000,2000)
        r = self.run_pairs(pairs)
        self.assertEqual(r['raw']['outside100'], 1)
        self.assertEqual(r['trend4']['changed_pairs'], 1)
        self.assertEqual(r['trend4']['range_uv'], [[1560,1560],[1560,1560]])
        r = self.run_pairs([(1500+i*10,1550+i*10) for i in range(12)])
        self.assertEqual(r['trend4']['changed_pairs'], 0)
        self.assertEqual(r['trend4']['range_uv'], r['raw']['range_uv'])

    def test_invalid_source_codes_rejected(self):
        for text in ('1560 1560\n4096 1560\n', '1560 1560\n'):
            p = subprocess.run([str(replay.EXE)], input=text, text=True, capture_output=True)
            self.assertNotEqual(p.returncode, 0)

if __name__ == '__main__': unittest.main()
