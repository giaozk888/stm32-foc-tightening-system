"""No hardware: count-only image/B844 and default-strict raw decoder."""
import struct
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
import motor_ident_rs_reject_count_board as selected
import motor_ident_reject_board as reject
import test_motor_identification_board as old


class RsRejectCountBoardTests(unittest.TestCase):
    def test_pins_baseline_default_no_devices(self):
        self.assertEqual(len(selected.image()),215132)
        with patch.dict(selected.base.__dict__,{}):
            selected.configure();self.assertEqual(selected.base.EXPECT_META[2:6],(2,0,0,844))
        p=subprocess.run([sys.executable,str(ROOT/'tools/motor_ident_rs_reject_count_board.py')],
                         capture_output=True,text=True,timeout=15)
        self.assertEqual(p.returncode,0,p.stdout+p.stderr);self.assertIn('B844, no devices',p.stdout)

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
            selected.previous.previous.motion(b,row)
        self.assertEqual(b.calls.count(selected.run.COMMAND),1)
        self.assertIn('MOTOR TEST STOP',b.calls);self.assertIn('ANALOG SAFE',b.calls)
        self.assertNotIn('START',b.calls)

    def test_explicit_opt_in_decoder_and_saved_evidence(self):
        ram=bytearray(1740);struct.pack_into('<2I2H4B',ram,1644,300,4000,0,0,255,255,0,0)
        row=dict(ident_run={},acquisition_pass=True,
            current_reject_reply='OK REJECT=300 GOOD=4000 MAX_RUN=255 FIRST=0 REJECT_MAX=0 RUN_LIMIT=0 TOTAL_STOP=0 RUN_STOP=0 RUN_SAT=255')
        reject.extra_decode(row,ram,0,total_reject_stop=False,run_reject_stop=False)
        self.assertTrue(row['acquisition_pass'])
        self.assertEqual(row['ident_run']['current_admission']['RUN_STOP'],0)
        with self.assertRaises(ValueError):reject.extra_decode(row,ram,0,total_reject_stop=False)
        with patch.object(selected.previous.previous.previous.encoder_report,'decode_saved',return_value={'saved':True}) as decoder,\
             patch.object(selected.previous.reject_only,'extra_decode',side_effect=ValueError('quality')) as extra:
            with self.assertRaises(ValueError):selected.extra_decode(row,ram,0)
        decoder.assert_called_once_with(row,selected.ELF)
        extra.assert_called_once_with(row,ram,0,total_gap_stop=False,run_reject_stop=False)
        self.assertTrue(row['encoder_terminal_saved']['saved'])


if __name__=='__main__':unittest.main()
