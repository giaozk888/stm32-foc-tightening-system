import subprocess
import sys
from pathlib import Path
import unittest
from unittest.mock import patch
from test_torque_chain import ROOT
sys.path.insert(0,str(ROOT/'tools'))
import ka_sync_motion_board as board


class SyncMotionTests(unittest.TestCase):
    def test_only_original_owner_not_preflight_motion(self):
        with patch.object(board.sync.previous,'motion') as run,patch.object(board.sync,'no_motion') as no:
            board.motion(object(),{})
            run.assert_called_once();no.assert_not_called()

    def test_no_retry_and_only_exact_benign_terminal_accepted(self):
        with patch.object(board.base,'execute',side_effect=RuntimeError('protection')) as run,patch.object(board,'classify') as classify:
            with self.assertRaisesRegex(RuntimeError,'protection'):board.execute({},'fake',Path('fake'),b'')
            self.assertEqual(run.call_count,1);classify.assert_not_called()
        with patch.object(board.base,'execute',side_effect=RuntimeError(board.gain.EXPECTED_TERMINAL)),patch.object(board,'classify',return_value={}):
            row={};board.execute(row,'fake',Path('fake'),b'');self.assertTrue(row['pass_'])

    def test_quality_not_silently_relabelled_and_incomplete_never_passed(self):
        with patch.object(board.gain.prior,'metrics',return_value={}):
            row=dict(sync_saved=dict(complete_short_window=True,points=[{}]*64,all_observations_valid=False,
                current_minus_encoder_time_us={},publisher_max_us=.5,span_us=63000))
            self.assertFalse(board.classify(row)['source_alignment_data_valid'])
            row['sync_saved']['points']=[]
            with self.assertRaises(RuntimeError):board.classify(row)

    def test_files_only_default_and_confirmation_gates(self):
        p=subprocess.run([sys.executable,str(ROOT/'tools/ka_sync_motion_board.py')],text=True,capture_output=True)
        self.assertEqual(p.returncode,0,p.stdout+p.stderr);self.assertIn('no devices',p.stdout)
        with patch.object(board,'setup') as setup:
            for args in (['--prepare-off'],['--execute-powered','missing'],['--restore-b-drive-off','missing']):
                with self.assertRaises(SystemExit):board.main(args)
            setup.assert_not_called()


if __name__=='__main__':unittest.main()
