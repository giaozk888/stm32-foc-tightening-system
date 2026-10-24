"""No devices: pinned candidate/B812, stopped readout, one RS50 command."""
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
import motor_ident_no_travel_board as selected
import test_motor_identification_board as old


class NoTravelBoardTests(unittest.TestCase):
    def test_exact_files_baseline_and_no_device_default(self):
        self.assertEqual(len(selected.image()),213580)
        with patch.dict(selected.base.__dict__,{}):
            selected.configure()
            self.assertEqual(selected.base.EXPECT_META[2:6],(2,0,0,812))
            self.assertEqual(selected.base.old.zero.digest(selected.base.baseline()),selected.BASE_SHA)
        p=subprocess.run([sys.executable,str(ROOT/'tools/motor_ident_no_travel_board.py')],
                         capture_output=True,text=True,timeout=15)
        self.assertEqual(p.returncode,0,p.stdout+p.stderr)
        self.assertIn('B812, no devices',p.stdout)

    def test_stopped_readout_one_rs50_no_advance(self):
        class Board(old.FakeBoard):
            def command(self,cmd,*args):
                if cmd=='MOTOR TEST IDENT GEOMETRY':
                    self.calls.append(cmd); return '1 OK TRAVEL_EXIT=OFF'
                if cmd=='MOTOR TEST IDENT REJECT':
                    self.calls.append(cmd); return '1 OK REJECT=0 GOOD=1 MAX_RUN=0 REJECT_MAX=16 RUN_LIMIT=3 FIRST=0'
                return super().command(cmd,*args)
        board=Board(); row={'postflight':{}}
        with old.IdentBoardTests().motion_patches(),patch.object(selected.run,'EXTRA_READOUT',selected.extra_readout):
            selected.run.motion(board,row)
        self.assertEqual(board.calls.count(selected.run.COMMAND),1)
        self.assertNotIn('START',board.calls)
        self.assertLess(board.calls.index('ANALOG SAFE'),board.calls.index('MOTOR TEST IDENT REJECT'))
        self.assertFalse(any('RS 75' in c or 'IDENT LD' in c or 'IDENT LQ' in c for c in board.calls))

    def test_wrong_revision_rejected(self):
        with self.assertRaises(RuntimeError):
            selected.extra_readout(old.FakeBoard(),{'ident_replies':[]})


if __name__=='__main__':unittest.main()
