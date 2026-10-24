"""Bounded-reject adapter: no devices, exact B808 and immutable frame decode."""
import json
import struct
import subprocess
import sys
import unittest
from unittest.mock import patch
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
import motor_ident_reject_board as selected
import test_motor_identification_board as old


class RejectBoardTests(unittest.TestCase):
    def test_default_no_device_and_exact_b808(self):
        self.assertEqual(len(selected.image()),213580)
        with patch.dict(selected.base.__dict__,{}):
            selected.configure()
            self.assertEqual(selected.base.EXPECT_META[2:6],(2,0,0,808))
            self.assertEqual(selected.base.old.zero.digest(selected.base.baseline()),selected.BASE_SHA)
        p=subprocess.run([sys.executable,str(ROOT/'tools/motor_ident_reject_board.py')],
            capture_output=True,text=True,timeout=10)
        self.assertEqual(p.returncode,0,p.stdout+p.stderr)
        self.assertIn('B808, no devices',p.stdout)

    def test_stopped_extension_decode_and_wire_mismatch(self):
        ram=bytearray(1660)
        struct.pack_into('<3I8f4B',ram,1596,168,157183,157182,.05,0,.25,-.01,.004,0,1.2,0,1,2,3,0)
        struct.pack_into('<2I2H4B',ram,1644,1,7997,1700,1500,0,1,0,1)
        row=dict(ident_run={},acquisition_pass=True,
            current_reject_reply='OK MID REJECT=1 GOOD=7997 MAX_RUN=1 FIRST=1')
        selected.extra_decode(row,ram,0)
        self.assertEqual(row['first_current_reject']['raw_u'],1700)
        self.assertAlmostEqual(row['first_current_reject']['id'],.25)
        self.assertEqual(row['ident_run']['current_admission']['REJECT'],1)
        row['current_reject_reply']='OK MID REJECT=2 GOOD=7997 MAX_RUN=1 FIRST=1'
        with self.assertRaises(ValueError):selected.extra_decode(row,ram,0)

    def test_readout_after_off_and_only_one_rs50(self):
        class Board(old.FakeBoard):
            def command(self,cmd,*args):
                if cmd=='MOTOR TEST IDENT REJECT':
                    self.calls.append(cmd);return '1 OK MID REJECT=1 GOOD=7997 RUN=0 MAX_RUN=1 REJECT_MAX=16 RUN_LIMIT=3 FIRST=1'
                if cmd=='MOTOR TEST IDENT REJECT ROW':
                    self.calls.append(cmd);return '1 OK MID FIRST_US=168 SEQ=157183 RAW_U=1700 RAW_V=1500 D_UA=250000 Q_UA=0'
                return super().command(cmd,*args)
        fixture=old.IdentBoardTests();board=Board();row={'postflight':{}}
        with fixture.motion_patches(),patch.object(selected.run,'EXTRA_READOUT',selected.extra_readout):
            selected.run.motion(board,row)
        self.assertEqual(board.calls.count(selected.run.COMMAND),1)
        self.assertNotIn('START',board.calls)
        self.assertLess(board.calls.index('ANALOG SAFE'),board.calls.index('MOTOR TEST IDENT REJECT'))
        self.assertIn('first_reject_reply',row)


if __name__=='__main__':unittest.main()
