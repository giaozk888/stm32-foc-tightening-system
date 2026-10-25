from pathlib import Path
import sys
import unittest
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
import dob_window75_board as b
class BoardTests(unittest.TestCase):
    def test_exact_pinned_files_only(self):self.assertEqual(len(b.image()),227520)
    def test_physical_gates_before_configuration(self):
        for args in (['--stage-off'],['--execute-powered','missing'],['--restore-b-drive-off','missing']):
            with patch.object(b,'configure') as configure:
                with self.assertRaises(SystemExit):b.main(args)
                configure.assert_not_called()
    def test_window_and_warmup_checked_before_existing_start_path(self):
        class Board:
            def __init__(self,bad=False):self.bad=bad;self.calls=[]
            def command(self,c):
                self.calls.append(c)
                if c.endswith('FB CFG'):values=dict(b.normal.FB_CONFIG,ON='0')
                elif c.endswith('WINDOW CFG'):values=dict(b.WINDOW,WINDOW_MS='100' if self.bad else '75')
                else:values=b.WARM
                return 'OK '+' '.join(k+'='+v for k,v in values.items())
        with patch.object(b.previous.prior,'motion') as original:
            board=Board();b.motion(board,dict(postflight={}))
            self.assertEqual(board.calls[:3],['MOTOR TEST MECH DOB FB CFG','MOTOR TEST MECH DOB WINDOW CFG','MOTOR TEST MECH DOB WARM CFG'])
            original.assert_called_once();original.reset_mock()
            with self.assertRaises(RuntimeError):b.motion(Board(True),dict(postflight={}))
            original.assert_not_called()
if __name__=='__main__':unittest.main()
