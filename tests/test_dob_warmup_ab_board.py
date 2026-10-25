from pathlib import Path
import sys
import unittest
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
import dob_warmup_ab_board as b
class BoardTests(unittest.TestCase):
    def test_pinned_files_only_and_plan(self):
        self.assertEqual(len(b.image()),227316);self.assertEqual(b.SCHEDULE,(5,3,5,3))
    def test_physical_gates_before_any_configuration(self):
        for args in (['--stage-off'],['--execute-four','missing'],['--restore-b-drive-off','missing']):
            with patch.object(b,'configure') as configure:
                with self.assertRaises(SystemExit):b.main(args)
                configure.assert_not_called()
    def test_select_and_readback_before_old_power_path(self):
        class Board:
            def __init__(self,bad=False):self.commands=[];self.tau=5;self.bad=bad
            def command(self,c):
                self.commands.append(c)
                if c.endswith('FB CFG'):return 'OK DOBFB '+' '.join(k+'='+v for k,v in dict(b.normal.FB_CONFIG,ON='0').items())
                if 'SET ' in c:self.tau=int(c[-1])
                return 'OK DOBWARM '+' '.join(k+'='+v for k,v in dict(b.CONFIG,TAU=str(5 if self.bad else self.tau)).items())
        with patch.object(b.prior,'motion') as original:
            row=dict(warmup_tau_requested=3,postflight={});board=Board();b.motion(board,row)
            self.assertEqual(board.commands[:4],['MOTOR TEST MECH DOB FB CFG','MOTOR TEST MECH DOB WARM CFG',
                'MOTOR TEST MECH DOB WARM SET 3','MOTOR TEST MECH DOB WARM CFG']);original.assert_called_once()
            original.reset_mock()
            with self.assertRaises(RuntimeError):b.motion(Board(True),row)
            original.assert_not_called()
    def test_real_fault_stops_batch_without_retry(self):
        parent=dict(baseline_restore_receipt=str(b.ROOT_RESTORE))
        with patch.object(b.normal,'ORIGINAL_EXECUTE',side_effect=RuntimeError('Protection fault; no retry')) as execute,patch.object(b.base.old.prior,'checkpoint'):
            with self.assertRaisesRegex(RuntimeError,'Protection fault'):b.run_four(Path('unused'),parent,b'')
            self.assertEqual(execute.call_count,1);self.assertEqual(len(parent['attempts']),1)
    def test_four_separate_runs_only_follow_validated_safe_completion(self):
        parent=dict(baseline_restore_receipt=str(b.ROOT_RESTORE));seen=[]
        def execute(row,name,source,data):
            seen.append(row['warmup_tau_requested'])
            row.update(trend_capture=dict(coverage=dict(observer_counts_match=True,full_observed_run=True)),
                saturation_audit=dict(warmup_frames=500),final_cpu_halted=True)
        with patch.object(b.normal,'ORIGINAL_EXECUTE',side_effect=execute),patch.object(b.normal,'classify',return_value={}),patch.object(b.base.old.prior,'checkpoint'):
            b.run_four(Path('stage'),parent,b'')
        self.assertEqual(seen,[5,3,5,3]);self.assertTrue(parent['pass_']);self.assertEqual(len(parent['runs']),4)
if __name__=='__main__':unittest.main()
