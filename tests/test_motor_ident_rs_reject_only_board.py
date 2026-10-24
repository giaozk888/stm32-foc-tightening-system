"""No devices: B828 pins; total>16 not host-failed; explicit disabled policy."""
import subprocess
import sys
import struct
import unittest
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
import motor_ident_rs_reject_only_board as selected
import test_motor_identification_board as old
POLICY='OK MID RS_DT_MAX=100 L_DT_MAX=55 DT_MIN=45 GAP_DT_PER_SEQ_MAX=55'


class RejectOnlyBoardTests(unittest.TestCase):
    def test_pins_and_default_files_only(self):
        self.assertEqual(len(selected.image()),214628)
        with patch.dict(selected.base.__dict__,{}):
            selected.configure()
            self.assertEqual(selected.base.EXPECT_META[2:6],(2,0,0,828))
            self.assertEqual(selected.base.old.zero.digest(selected.base.baseline()),selected.BASE_SHA)
        p=subprocess.run([sys.executable,str(ROOT/'tools/motor_ident_rs_reject_only_board.py')],
                         capture_output=True,text=True,timeout=15)
        self.assertEqual(p.returncode,0,p.stdout+p.stderr)
        self.assertIn('B828, no devices',p.stdout)

    def test_one_rs50_output_off_before_readout(self):
        class Board(old.FakeBoard):
            def command(self,cmd,*args):
                lines={'MOTOR TEST IDENT TIME POLICY':POLICY,
                    'MOTOR TEST IDENT GEOMETRY':'OK TRAVEL_EXIT=OFF',
                    'MOTOR TEST IDENT REJECT':'OK REJECT=17 GOOD=701 MAX_RUN=1 REJECT_MAX=0 RUN_LIMIT=3 FIRST=1 TOTAL_STOP=0',
                    'MOTOR TEST IDENT REJECT ROW':'OK MID FIRST_US=5711',
                    'MOTOR TEST IDENT TIMING':'OK TV=0',
                    'MOTOR TEST IDENT TIMING CONTEXT':'OK CV=0',
                    'MOTOR TEST IDENT RS GAPS':'OK RS_GAPS=0 SKIPPED=0 MAX_GAP=0 BUDGET=16 RUN_LIMIT=2'}
                if cmd in lines:self.calls.append(cmd);return lines[cmd]
                return super().command(cmd,*args)
        b=Board();row={'postflight':{}}
        with old.IdentBoardTests().motion_patches(),patch.object(selected.run,'EXTRA_READOUT',selected.extra_readout):
            selected.previous.motion(b,row)
        self.assertEqual(b.calls.count(selected.run.COMMAND),1)
        self.assertNotIn('START',b.calls)
        self.assertLess(b.calls.index('ANALOG SAFE'),b.calls.index('MOTOR TEST IDENT REJECT'))

    def test_gt16_accepted_and_old_policy_rejected(self):
        raw=bytearray(1740);struct.pack_into('<2I2H4B',raw,1644,17,701,0,0,0,1,0,1)
        row=dict(ident_run={},acquisition_pass=True,
            current_reject_reply='OK REJECT=17 GOOD=701 MAX_RUN=1 FIRST=1 REJECT_MAX=0 RUN_LIMIT=3 TOTAL_STOP=0',
            timing_failure_reply='OK TV=0 PS=0 PU=0 S=0 U=0 DS=0 DT=0 WHY=0',
            timing_context_reply='OK CV=0 ADC=0 FRAME=0 PAIR_US=0 HB=0 HN=0 PATH=0',
            rs_gap_reply='OK RS_GAPS=0 SKIPPED=0 MAX_GAP=0 BUDGET=16 RUN_LIMIT=2',
            time_policy_reply=POLICY,time_policy_post=selected.previous.policy(POLICY))
        with patch.object(selected.run.analysis,'guard') as guard:
            selected.extra_decode(row,raw,0);guard.assert_called_once()
        self.assertTrue(row['acquisition_pass'])
        self.assertEqual(row['ident_run']['current_admission']['TOTAL_STOP'],0)
        row['current_reject_reply']=row['current_reject_reply'].replace('TOTAL_STOP=0','TOTAL_STOP=1')
        with self.assertRaises(ValueError):selected.extra_decode(row,raw,0)


if __name__=='__main__':unittest.main()
