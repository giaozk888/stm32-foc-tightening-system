"""Files/transport mocks only; no debugger/serial/motor access."""
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
import current_step_ident_policy_board as selected
from test_current_step_ab_board import FakeBoard
import test_current_step_ab_board as legacy

POLICY='OK ENC POLICY=2 TERMINAL_FIX=1 WARN_US=200 DEADLINE_US=400 SCHED_US=200 PERIOD_US=1000 AGE_US=1500 CONTROL_US=2500 SLOW_N=3 OK_MAX_US=215'

class Board(FakeBoard):
    def command(self,cmd,*args):
        if cmd==selected.POLICY_COMMAND:
            self.calls.append(cmd)
            return POLICY.replace('SLOW_N=3','SLOW_N=4') if self.active else POLICY
        return super().command(cmd,*args)

class PolicyBoardTests(unittest.TestCase):
    def tearDown(self):
        for key,value in selected.ORIGINALS.items():setattr(selected.step,key,value)
        selected.gate.LEGACY['configure']()

    def test_exact_image_b900_baseline_and_default_no_devices(self):
        with patch.object(selected.base.hw,'debug') as debug,patch.object(selected.base.support.support,'open_port') as serial:
            self.assertEqual(len(selected.image()),214340)
            selected.configure()
            self.assertEqual(selected.base.EXPECT_META[2:6],(2,0,0,900))
            self.assertEqual(selected.base.SHA,selected.SHA)
            selected.base.baseline()
            debug.assert_not_called();serial.assert_not_called()
        p=subprocess.run([sys.executable,str(ROOT/'tools/current_step_ident_policy_board.py')],
                         capture_output=True,text=True,timeout=15)
        self.assertEqual(p.returncode,0,p.stdout+p.stderr)
        self.assertIn('B900 baseline; no devices',p.stdout)

    def test_policy_before_one_command_then_stop_and_postread(self):
        board=Board();row=dict(postflight={})
        with legacy.StepBoardTests().fixture():selected.motion(board,row)
        self.assertLess(board.calls.index(selected.POLICY_COMMAND),board.calls.index(selected.step.COMMAND))
        self.assertEqual(board.calls.count(selected.step.COMMAND),1)
        self.assertEqual(board.calls.count(selected.POLICY_COMMAND),2)
        self.assertEqual(row['encoder_slow_count_delta'],1)
        self.assertNotIn('START',board.calls)
        self.assertIn('MOTOR TEST STOP',board.calls)

    def test_new_policy_image_restore_b904_requires_full_identity(self):
        receipt=ROOT/'tmp/current-step-ab-restore-1792574655503905800.json'
        with patch.object(selected.base.hw,'debug') as debug,patch.object(selected.base.support.support,'open_port') as serial:
            selected.configure(receipt)
            self.assertEqual(selected.base.EXPECT_META[2:6],(2,0,0,904))
            self.assertEqual(selected.base.BASE_RESTORE_RECEIPT,receipt.resolve())
            self.assertEqual(selected.base.baseline()[0x8000:0x8000+len(selected.image())],selected.image())
            debug.assert_not_called();serial.assert_not_called()

    def test_wrong_policy_cannot_excite(self):
        for old,new in (('DEADLINE_US=400','DEADLINE_US=200'),('SCHED_US=200','SCHED_US=400'),
                        ('AGE_US=1500','AGE_US=2000'),('TERMINAL_FIX=1','TERMINAL_FIX=0')):
            with self.assertRaises(RuntimeError):selected.policy(POLICY.replace(old,new))
        board=Board();row=dict(postflight={})
        with patch.object(selected,'policy',side_effect=RuntimeError('wrong')):
            with self.assertRaises(RuntimeError):selected.motion(board,row)
        self.assertNotIn(selected.step.COMMAND,board.calls)

    def test_bad_ack_never_retries_and_flags_required(self):
        board=Board(True);row=dict(postflight={})
        with legacy.StepBoardTests().fixture(),self.assertRaises(TimeoutError):selected.motion(board,row)
        self.assertEqual(board.calls.count(selected.step.COMMAND),1)
        self.assertIn('ANALOG SAFE',board.calls)
        with patch.object(selected.base.hw,'debug') as debug,patch.object(selected.base.support.support,'open_port') as serial:
            for args in (['--stage-off'],['--execute-powered','unused'],['--restore-b-drive-off','unused']):
                with self.assertRaises(SystemExit):selected.main(args)
            debug.assert_not_called();serial.assert_not_called()

if __name__=='__main__':unittest.main()
