"""No devices: exact B816, one RS50, stopped snapshot UART/RAM parity."""
import subprocess
import sys
import struct
import unittest
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
import motor_ident_timing_board as selected
import test_motor_identification_board as old


class TimingBoardTests(unittest.TestCase):
    def test_pins_and_default_files_only(self):
        self.assertEqual(len(selected.image()),214156)
        with patch.dict(selected.base.__dict__,{}):
            selected.configure()
            self.assertEqual(selected.base.EXPECT_META[2:6],(2,0,0,816))
            self.assertEqual(selected.base.old.zero.digest(selected.base.baseline()),selected.BASE_SHA)
        p=subprocess.run([sys.executable,str(ROOT/'tools/motor_ident_timing_board.py')],
                         capture_output=True,text=True,timeout=15)
        self.assertEqual(p.returncode,0,p.stdout+p.stderr)
        self.assertIn('B816, no devices',p.stdout)

    def test_one_excitation_then_off_before_timing_readout(self):
        class Board(old.FakeBoard):
            def command(self,cmd,*args):
                lines={'MOTOR TEST IDENT GEOMETRY':'OK TRAVEL_EXIT=OFF',
                    'MOTOR TEST IDENT REJECT':'OK REJECT=0 GOOD=1 MAX_RUN=0 REJECT_MAX=16 RUN_LIMIT=3 FIRST=0',
                    'MOTOR TEST IDENT TIMING':'OK TV=1 DS=1 DT=68 WHY=4',
                    'MOTOR TEST IDENT TIMING CONTEXT':'OK CV=1'}
                if cmd in lines:self.calls.append(cmd);return lines[cmd]
                return super().command(cmd,*args)
        board=Board();row={'postflight':{}}
        with old.IdentBoardTests().motion_patches(),patch.object(selected.run,'EXTRA_READOUT',selected.extra_readout):
            selected.run.motion(board,row)
        self.assertEqual(board.calls.count(selected.run.COMMAND),1)
        self.assertNotIn('START',board.calls)
        self.assertLess(board.calls.index('ANALOG SAFE'),board.calls.index('MOTOR TEST IDENT TIMING'))

    def test_frozen_wire_ram_parity(self):
        raw=bytearray(1724)
        struct.pack_into('<15I',raw,1660,10,100,11,168,1,68,4,1,11,11,168,0,0,1,1)
        row=dict(ident_run={},current_reject_reply='OK REJECT=0 GOOD=0 MAX_RUN=0 FIRST=0',
            timing_failure_reply='OK TV=1 PS=10 PU=100 S=11 U=168 DS=1 DT=68 WHY=4',
            timing_context_reply='OK CV=1 ADC=11 FRAME=11 PAIR_US=168 HB=0 HN=0 PATH=1')
        selected.extra_decode(row,raw,0)
        self.assertEqual(row['ident_timing_failure']['classification'],'SOFTWARE_TIMESTAMP_INTERVAL')
        row['timing_failure_reply']=row['timing_failure_reply'].replace('DT=68','DT=50')
        with self.assertRaises(ValueError):selected.extra_decode(row,raw,0)


if __name__=='__main__':unittest.main()
