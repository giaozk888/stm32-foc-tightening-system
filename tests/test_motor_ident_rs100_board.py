"""No devices: B824/image pins, pre-command policy, explicit 100us RAM decode."""
import subprocess
import sys
import struct
import unittest
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
import motor_ident_rs100_board as selected
import test_motor_identification_board as old
POLICY='OK MID RS_DT_MAX=100 L_DT_MAX=55 DT_MIN=45 GAP_DT_PER_SEQ_MAX=55'


class Rs100BoardTests(unittest.TestCase):
    def test_pins_and_files_only_default(self):
        self.assertEqual(len(selected.image()),214596)
        with patch.dict(selected.base.__dict__,{}):
            selected.configure()
            self.assertEqual(selected.base.EXPECT_META[2:6],(2,0,0,824))
            self.assertEqual(selected.base.old.zero.digest(selected.base.baseline()),selected.BASE_SHA)
        p=subprocess.run([sys.executable,str(ROOT/'tools/motor_ident_rs100_board.py')],
                         capture_output=True,text=True,timeout=15)
        self.assertEqual(p.returncode,0,p.stdout+p.stderr)
        self.assertIn('B824, no devices',p.stdout)

    def test_policy_checked_before_only_one_rs50_and_wrong_policy_no_command(self):
        class Board(old.FakeBoard):
            def command(self,cmd,*args):
                if cmd=='MOTOR TEST IDENT TIME POLICY':self.calls.append(cmd);return POLICY
                return super().command(cmd,*args)
        b=Board();row={'postflight':{}}
        with old.IdentBoardTests().motion_patches(),patch.object(selected.run,'EXTRA_READOUT',None):
            selected.motion(b,row)
        self.assertEqual(b.calls.count(selected.run.COMMAND),1)
        self.assertLess(b.calls.index('MOTOR TEST IDENT TIME POLICY'),b.calls.index(selected.run.COMMAND))
        b=old.FakeBoard()
        with self.assertRaises(ValueError):selected.motion(b,{})
        self.assertNotIn(selected.run.COMMAND,b.calls)

    def test_100us_flags_are_not_decoded_as_historical55(self):
        raw=bytearray(1740)
        struct.pack_into('<15I',raw,1660,10,100,12,200,2,100,1,1,12,12,200,0,0,1,1)
        row=dict(ident_run={},current_reject_reply='OK REJECT=0 GOOD=0 MAX_RUN=0 FIRST=0',
                 timing_failure_reply='OK TV=1 PS=10 PU=100 S=12 U=200 DS=2 DT=100 WHY=1',
                 timing_context_reply='OK CV=1 ADC=12 FRAME=12 PAIR_US=200 HB=0 HN=0 PATH=1',
                 rs_gap_reply='OK RS_GAPS=0 SKIPPED=0 MAX_GAP=0 BUDGET=16 RUN_LIMIT=2',
                 time_policy_reply=POLICY,time_policy_post=selected.policy(POLICY))
        selected.extra_decode(row,raw,0)
        self.assertEqual(row['ident_timing_failure']['failed_conditions'],['sequence_delta_not_1'])
        row['time_policy_reply']=POLICY.replace('RS_DT_MAX=100','RS_DT_MAX=55')
        with self.assertRaises(ValueError):selected.extra_decode(row,raw,0)


if __name__=='__main__':unittest.main()
