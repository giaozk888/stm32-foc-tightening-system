"""No hardware: pinned count-only image/B840; default old decode stays strict."""
import struct
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
import motor_ident_rs_gap_count_board as selected
import motor_ident_rs_gap_board as gap
import test_motor_identification_board as old


class RsGapCountBoardTests(unittest.TestCase):
    def test_pins_baseline_default_no_devices(self):
        self.assertEqual(len(selected.image()),215076)
        with patch.dict(selected.base.__dict__,{}):
            selected.configure();self.assertEqual(selected.base.EXPECT_META[2:6],(2,0,0,840))
        p=subprocess.run([sys.executable,str(ROOT/'tools/motor_ident_rs_gap_count_board.py')],
                         capture_output=True,text=True,timeout=15)
        self.assertEqual(p.returncode,0,p.stdout+p.stderr);self.assertIn('B840, no devices',p.stdout)

    def test_only_one_rs50_and_original_closure(self):
        class Board(old.FakeBoard):
            def command(self,cmd,*args):
                if cmd=='MOTOR TEST IDENT ENCODER TIME':
                    self.calls.append(cmd)
                    return 'OK POLICY=2 WARN_US=200 DEADLINE_US=400 SCHED_US=200 PERIOD_US=1000 AGE_US=1500 CONTROL_US=2500 SLOW_N=0 OK_MAX_US=130'
                if cmd=='MOTOR TEST IDENT TIME POLICY':
                    self.calls.append(cmd)
                    return 'OK RS_DT_MAX=100 L_DT_MAX=55 DT_MIN=45 GAP_DT_PER_SEQ_MAX=55'
                return super().command(cmd,*args)
        b=Board();row={'postflight':{}}
        with old.IdentBoardTests().motion_patches(),patch.object(selected.run,'EXTRA_READOUT',None):
            selected.previous.motion(b,row)
        self.assertEqual(b.calls.count(selected.run.COMMAND),1)
        self.assertIn('MOTOR TEST STOP',b.calls);self.assertIn('ANALOG SAFE',b.calls)
        self.assertNotIn('START',b.calls)

    def test_explicit_opt_in_decoder_and_saved_evidence(self):
        ram=bytearray(1740);struct.pack_into('<4I',ram,1724,1,40,40,1)
        row=dict(ident_run={},rs_gap_reply='OK RS_GAPS=40 SKIPPED=40 MAX_GAP=1 BUDGET=0 RUN_LIMIT=2 TOTAL_STOP=0')
        with patch.object(gap.previous,'extra_decode'):
            gap.extra_decode(row,ram,0,total_gap_stop=False)
            self.assertEqual(row['ident_run']['rs_gap_admission']['TOTAL_STOP'],0)
            with self.assertRaises(ValueError):gap.extra_decode(row,ram,0)
        with patch.object(selected.previous.previous.encoder_report,'decode_saved',return_value={'saved':True}) as decoder,\
             patch.object(selected.reject_only,'extra_decode',side_effect=ValueError('quality')) as extra:
            with self.assertRaises(ValueError):selected.extra_decode(row,ram,0)
        decoder.assert_called_once_with(row,selected.ELF)
        extra.assert_called_once_with(row,ram,0,total_gap_stop=False)
        self.assertTrue(row['encoder_terminal_saved']['saved'])


if __name__=='__main__':unittest.main()
