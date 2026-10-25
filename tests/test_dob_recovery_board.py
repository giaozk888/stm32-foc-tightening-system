from pathlib import Path
import sys
import unittest
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
import dob_recovery_board as b
class BoardTests(unittest.TestCase):
    def test_exact_image_files_only(self):self.assertEqual(len(b.image()),228712)
    def test_physical_gates_before_any_configuration(self):
        for args in (['--stage-off'],['--execute-powered','missing'],['--restore-b-drive-off','missing']):
            with patch.object(b,'configure') as configure:
                with self.assertRaises(SystemExit):b.main(args)
                configure.assert_not_called()
    def test_timing_config_checked_before_original_start_route(self):
        class Board:
            def __init__(self,bad=False):self.bad=bad;self.calls=[]
            def command(self,c):
                self.calls.append(c);values=dict(b.CFG,WINDOW_MS='100' if self.bad else '75')
                return 'OK DOBREC '+' '.join(k+'='+v for k,v in values.items())
        with patch.object(b,'OLD_MOTION') as original:
            good=Board();b.motion(good,dict(postflight={}));original.assert_called_once()
            self.assertEqual(good.calls,['MOTOR TEST MECH DOB RECOVERY CFG']*2)
            original.reset_mock()
            with self.assertRaises(RuntimeError):b.motion(Board(True),dict(postflight={}))
            original.assert_not_called()
    def test_preflight_without_start_does_not_invent_recovery_data(self):
        row=dict(start_attempts=0)
        with patch.object(b,'OLD_DECODE'),patch.object(b.recovery,'load') as load:
            b.decode(row);load.assert_not_called();self.assertFalse(row['recovery_capture']['available'])
if __name__=='__main__':unittest.main()
