"""No device IO: exact timing candidate, policy gate and one-shot closure."""
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
import motor_ident_encoder_timing_board as selected
import test_motor_identification_board as old

POLICY='OK POLICY=2 WARN_US=200 DEADLINE_US=400 SCHED_US=200 PERIOD_US=1000 AGE_US=1500 CONTROL_US=2500 SLOW_N=2 OK_MAX_US=203'


class EncoderTimingBoardTests(unittest.TestCase):
    def test_pins_and_default_no_device(self):
        self.assertEqual(len(selected.image()),215060)
        with patch.dict(selected.base.__dict__,{}):
            selected.configure()
            self.assertEqual(selected.base.EXPECT_META[2:6],(2,0,0,836))
        p=subprocess.run([sys.executable,str(ROOT/'tools/motor_ident_encoder_timing_board.py')],
                         capture_output=True,text=True,timeout=15)
        self.assertEqual(p.returncode,0,p.stdout+p.stderr)
        self.assertIn('B836, no devices',p.stdout)

    def test_policy_before_single_rs50_then_close(self):
        class Board(old.FakeBoard):
            def command(self,cmd,*args):
                if cmd=='MOTOR TEST IDENT ENCODER TIME':
                    self.calls.append(cmd);return POLICY
                if cmd=='MOTOR TEST IDENT TIME POLICY':
                    self.calls.append(cmd)
                    return 'OK RS_DT_MAX=100 L_DT_MAX=55 DT_MIN=45 GAP_DT_PER_SEQ_MAX=55'
                return super().command(cmd,*args)
        b=Board();row={'postflight':{}}
        with old.IdentBoardTests().motion_patches(),patch.object(selected.run,'EXTRA_READOUT',None):
            selected.motion(b,row)
        self.assertEqual(b.calls.count(selected.run.COMMAND),1)
        self.assertLess(b.calls.index('MOTOR TEST IDENT ENCODER TIME'),b.calls.index(selected.run.COMMAND))
        self.assertIn('MOTOR TEST STOP',b.calls);self.assertIn('ANALOG SAFE',b.calls)
        self.assertNotIn('START',b.calls)
        b=Board()
        with patch.object(selected,'policy',side_effect=ValueError('wrong policy')):
            with self.assertRaises(ValueError):selected.motion(b,{'postflight':{}})
        self.assertNotIn(selected.run.COMMAND,b.calls)

    def test_policy_strict_and_same_elf_evidence_survives_quality_failure(self):
        self.assertEqual(selected.policy(POLICY)['DEADLINE_US'],'400')
        for old_value in ('DEADLINE_US=200','SCHED_US=400'):
            text=POLICY.replace('DEADLINE_US=400',old_value) if old_value.startswith('DEADLINE') else POLICY.replace('SCHED_US=200',old_value)
            with self.assertRaises(ValueError):selected.policy(text)
        row={}
        with patch.object(selected.previous.encoder_report,'decode_saved',return_value={'saved':True}) as decoder,\
             patch.object(selected.previous.previous,'extra_decode',side_effect=ValueError('quality')):
            with self.assertRaises(ValueError):selected.extra_decode(row,b'',0)
        decoder.assert_called_once_with(row,selected.ELF)
        self.assertTrue(row['encoder_terminal_saved']['saved'])


if __name__=='__main__':unittest.main()
