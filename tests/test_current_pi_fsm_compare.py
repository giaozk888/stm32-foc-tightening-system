import sys
from pathlib import Path
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
import current_pi_fsm_compare as comparison


class PiFsmCompareTests(unittest.TestCase):
    def test_exact_binary_and_ram_redecode_comparison_not_upgraded(self):
        r=comparison.report()
        self.assertFalse(r['same_batch_ab']);self.assertFalse(r['hardware_access'])
        self.assertFalse(r['parameter_identification_qualified'])
        self.assertEqual(r['old']['recipe'],r['new']['recipe'])
        self.assertEqual(r['new']['terminal'],'RUNDOWN_TIMEOUT')
        self.assertEqual(r['new']['contact'],'0')
        self.assertAlmostEqual(r['new']['metrics']['accel_mae_rpm'],9.1717,places=3)
        self.assertAlmostEqual(r['old']['metrics']['accel_mae_rpm'],14.2128,places=3)
        self.assertEqual(r['new']['timing']['actual_late_count'],0)


if __name__=='__main__':unittest.main()
