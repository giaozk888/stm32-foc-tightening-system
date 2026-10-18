"""File-only / mock regressions. No physical board access."""
from pathlib import Path
import sys
import unittest
from unittest.mock import patch,Mock

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
import rolling_trace_closed_loop_motion as board
import test_pipeline_closed_loop_trial as ready


class MotionTests(unittest.TestCase):
    def test_default_files_only(self):
        with patch.object(sys,'argv',['motion']),patch.object(board,'baseline') as base:
            self.assertEqual(board.main(),0)
            base.assert_not_called()

    def test_physical_gates_before_files(self):
        for args in (['--inspect-off'],['--execute-from-inspection','x']):
            with patch.object(sys,'argv',['motion',*args]),patch.object(board.rolling,'image') as image:
                with self.assertRaises(SystemExit): board.main()
                image.assert_not_called()

    def test_stale_or_foreign_inspection_rejected(self):
        with self.assertRaises(ValueError): board.load_inspection(Path('foreign.json'))

    def test_inspect_never_resets_or_starts(self):
        row={}
        with patch.object(board,'debug',return_value='off') as debug,\
                patch.object(board,'check_off',return_value={}):
            board.inspect(row,'test',Path('baseline.bin'))
        commands=debug.call_args.args[1]
        self.assertFalse(any('reset' in c or 'START' in c or 'flash write' in c for c in commands))
        self.assertEqual(row['reset_attempts'],0)

    def test_ready_failure_never_invokes_motion_and_always_stops(self):
        row={'steps':[],'samples':[]}
        port=Mock(); port.is_open=True
        sample=ready.good(); sample['status']['FLT']='1'
        with patch.object(board,'open_port',return_value=port),\
                patch.object(board.trial,'Console'),patch.object(board,'debug',return_value='off'),\
                patch.object(board.trial,'wait_health_confirmation'),\
                patch.object(board.trial,'sample',return_value=sample),\
                patch.object(board,'motion') as motion,\
                patch.object(board,'emergency_off') as off,\
                patch.object(Path,'read_bytes',return_value=b'unchanged'),\
                patch.object(board,'latest_meta',return_value=board.META),\
                patch.object(board,'check_off',return_value={'VTOR':0x08008000}):
            with self.assertRaises(RuntimeError): board.execute(row,'test',Path('base.bin'),b'unchanged')
        motion.assert_not_called(); off.assert_called_once(); port.close.assert_called_once()

    def test_runner_bound_and_invoked_once(self):
        row={}
        output='IN_MOTION T=0.1s OK CTRL=12.0rpm\nPosition change: +2.00 deg'
        with patch.object(board.subprocess,'run',return_value=Mock(returncode=0,stdout=output,stderr='')) as run:
            board.motion(row)
        run.assert_called_once()
        args=run.call_args.args[0]
        self.assertEqual(args[-4:],['--expected-slot','A','--target-rpm','20'])
        self.assertEqual(run.call_args.kwargs['timeout'],25)
        self.assertTrue(row['movement_feedback_observed'])

    def test_fault_or_missing_movement_is_not_pass(self):
        for code,out in ((1,'Fault during motion'),(0,'IN_MOTION CTRL=0.0rpm\nPosition change: +0.00 deg')):
            row={}
            with patch.object(board.subprocess,'run',return_value=Mock(returncode=code,stdout=out,stderr='')):
                with self.assertRaises(RuntimeError): board.motion(row)
            self.assertEqual(row['original_start_runner_invocations'],1)
            self.assertNotIn('short_start_stop_pass',row)


if __name__ == '__main__':
    unittest.main()
