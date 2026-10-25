import sys
import unittest
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
import dob_saturation_continue_board as b

class SaturationBoardTests(unittest.TestCase):
    def test_new_exact_image_files_only(self):
        self.assertEqual(len(b.image()),226792)

    def test_missing_physical_confirmations_do_not_configure(self):
        for args in (['--stage-off'],['--execute-powered','missing'],['--restore-b-drive-off','missing']):
            with patch.object(b,'configure') as configure:
                with self.assertRaises(SystemExit):b.main(args)
                configure.assert_not_called()

    def test_estimate_only_configuration_checked_before_original_motion(self):
        class Board:
            def __init__(self,ff):self.ff=ff;self.commands=[]
            def command(self,c):
                self.commands.append(c)
                return 'OK DOBSAT '+' '.join(k+'='+v for k,v in dict(b.CONFIG,FB_ON_LIMIT=self.ff).items())
        with patch.object(b,'OLD_MOTION') as motion:
            with self.assertRaises(RuntimeError):b.motion(Board('1'),{'postflight':{}})
            motion.assert_not_called()
            good=Board('0');b.motion(good,{'postflight':{}});motion.assert_called_once()
            self.assertEqual(good.commands,['MOTOR TEST MECH DOB SAT CFG','MOTOR TEST MECH DOB SAT STATS'])

if __name__=='__main__':unittest.main()
