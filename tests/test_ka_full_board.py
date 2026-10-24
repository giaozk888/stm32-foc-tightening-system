from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
import ka_full_board as board

class FullBoardTests(unittest.TestCase):
    def test_default_no_device_exact_image_and_fresh_gates(self):
        p=subprocess.run([sys.executable,str(ROOT/'tools/ka_full_board.py')],text=True,capture_output=True)
        self.assertEqual(p.returncode,0,p.stdout+p.stderr);self.assertIn('no devices',p.stdout)
        with patch.object(board,'setup') as setup:
            for args in (['--prepare-off'],['--execute-powered','missing'],['--restore-b-drive-off','missing']):
                with self.assertRaises(SystemExit):board.main(args)
            setup.assert_not_called()

    def test_only_original_start_owner(self):
        with patch.object(board.previous.sync.previous,'motion') as owner:
            b=object();r={};board.motion(b,r);owner.assert_called_once_with(b,r)

    def test_no_retry_no_parameter_write_and_incomplete_preserved(self):
        with patch.object(board.base,'execute',side_effect=RuntimeError('protection')) as start:
            with self.assertRaisesRegex(RuntimeError,'protection'):board.execute({},'fake',Path('fake'),b'')
            self.assertEqual(start.call_count,1)
        with patch.object(board.gain.prior,'metrics',return_value={}):
            with self.assertRaises(RuntimeError):board.classify(dict(full_saved=dict(complete=False)))
        with patch.object(board.base,'execute',side_effect=RuntimeError(board.gain.EXPECTED_TERMINAL)),\
             patch.object(board,'classify',return_value={}),patch.object(board.report,'report',return_value={}):
            row=dict(full_saved={});board.execute(row,'fake',Path('fake'),b'');self.assertTrue(row['pass_'])

if __name__=='__main__':unittest.main()
