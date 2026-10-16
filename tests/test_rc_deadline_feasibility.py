"""Offline regression on the public timing evidence and deferred-plan policy."""
from pathlib import Path
import json
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]
RECEIPT = ROOT/'safety_backups/protected-closed-loop-20261014/rc-boundary-lite-trial-1792130588821995900.json'


class RcDeadlineFeasibilityTests(unittest.TestCase):
    def test_observed_same_cycle_deficit_is_not_50us_overrun(self):
        import sys
        sys.path.insert(0,str(ROOT/'tools'))
        from rc_deadline_feasibility import assess
        row=json.loads(RECEIPT.read_text('utf-8'))
        result=assess(row['sample'])
        self.assertEqual(result['samples'],104387)
        self.assertEqual(result['coarse_late'],3498)
        self.assertLess(result['observed_irq_max_us'],50)
        for frame in result['frames'].values():
            self.assertGreater(frame['current_bottom_deficit_us'],0)
            self.assertLess(frame['remaining_us'],20)
            self.assertGreater(frame['next_bottom_budget_us'],60)

    def test_deferred_plan_host_compiles_and_fail_closes(self):
        gcc=Path(r'D:\Qt\Tools\mingw1310_64\bin\gcc.exe')
        exe=ROOT/'tests/foc_adc_window_build/rc_deferred_plan.exe'
        exe.parent.mkdir(exist_ok=True)
        subprocess.run([str(gcc),'-std=c11','-O2','-Wall','-Wextra','-Werror',
            '-pedantic','-UNDEBUG','-I',str(ROOT/'firmware_common'),
            str(ROOT/'tests/foc_rc_deferred_plan_host.c'),'-o',str(exe)],check=True)
        subprocess.run([str(exe)],check=True)

    def test_repair_snapshot_has_no_new_adc_path(self):
        source=(ROOT/'firmware_common/protected_closed_loop.inc').read_text('utf-8')
        self.assertIn('"MOTOR TEST REPAIR SNAP"',source)
        formatter=source.split('static void ProtectedLoop_Command(',1)[1]
        self.assertIn('FocFp_Popcount(p.repair_window)',formatter)
        self.assertIn('uint32_t mask=__get_PRIMASK(); __disable_irq();',formatter)


if __name__ == '__main__': unittest.main()
