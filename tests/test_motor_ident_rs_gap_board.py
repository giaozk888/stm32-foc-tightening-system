"""No device IO: pinned B820/image, one RS50, stopped UART/RAM evidence."""
import subprocess
import sys
import struct
import unittest
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
import motor_ident_rs_gap_board as selected
import test_motor_identification_board as old


class RsGapBoardTests(unittest.TestCase):
    def test_pins_and_files_only_default(self):
        self.assertEqual(len(selected.image()),214452)
        with patch.dict(selected.base.__dict__,{}):
            selected.configure()
            self.assertEqual(selected.base.EXPECT_META[2:6],(2,0,0,820))
            self.assertEqual(selected.base.old.zero.digest(selected.base.baseline()),selected.BASE_SHA)
        p=subprocess.run([sys.executable,str(ROOT/'tools/motor_ident_rs_gap_board.py')],
                         capture_output=True,text=True,timeout=15)
        self.assertEqual(p.returncode,0,p.stdout+p.stderr)
        self.assertIn('B820, no devices',p.stdout)

    def test_one_excitation_then_off_before_gap_readout(self):
        class Board(old.FakeBoard):
            def command(self,cmd,*args):
                lines={'MOTOR TEST IDENT GEOMETRY':'OK TRAVEL_EXIT=OFF',
                    'MOTOR TEST IDENT REJECT':'OK REJECT=0 GOOD=1 MAX_RUN=0 REJECT_MAX=16 RUN_LIMIT=3 FIRST=0',
                    'MOTOR TEST IDENT TIMING':'OK TV=0',
                    'MOTOR TEST IDENT TIMING CONTEXT':'OK CV=0',
                    'MOTOR TEST IDENT RS GAPS':'OK RS_GAPS=1 SKIPPED=1 MAX_GAP=1 BUDGET=16 RUN_LIMIT=2'}
                if cmd in lines:self.calls.append(cmd);return lines[cmd]
                return super().command(cmd,*args)
        board=Board();row={'postflight':{}}
        with old.IdentBoardTests().motion_patches(),patch.object(selected.run,'EXTRA_READOUT',selected.extra_readout):
            selected.run.motion(board,row)
        self.assertEqual(board.calls.count(selected.run.COMMAND),1)
        self.assertNotIn('START',board.calls)
        self.assertLess(board.calls.index('ANALOG SAFE'),board.calls.index('MOTOR TEST IDENT RS GAPS'))

    def test_gap_binary_extension_and_wire_parity(self):
        raw=bytearray(1740);struct.pack_into('<4I',raw,1724,1,1,1,1)
        row=dict(ident_run={},current_reject_reply='OK REJECT=0 GOOD=0 MAX_RUN=0 FIRST=0',
                 timing_failure_reply='OK TV=0 PS=0 PU=0 S=0 U=0 DS=0 DT=0 WHY=0',
                 timing_context_reply='OK CV=0 ADC=0 FRAME=0 PAIR_US=0 HB=0 HN=0 PATH=0',
                 rs_gap_reply='OK RS_GAPS=1 SKIPPED=1 MAX_GAP=1 BUDGET=16 RUN_LIMIT=2')
        selected.extra_decode(row,raw,0)
        self.assertEqual(row['ident_run']['rs_gap_admission']['SKIPPED'],1)
        row['rs_gap_reply']=row['rs_gap_reply'].replace('SKIPPED=1','SKIPPED=2')
        with self.assertRaises(ValueError):selected.extra_decode(row,raw,0)


if __name__=='__main__':unittest.main()
