"""Transport mocks/files only; NEVER accesses a debugger or serial device."""
from contextlib import ExitStack
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
import current_step_ab_board as b


class FakeBoard:
    def __init__(self,refuse=False):self.calls=[];self.active=False;self.refuse=refuse
    def command(self,cmd,*args):
        self.calls.append(cmd)
        if cmd==b.COMMAND:
            self.active=True
            if self.refuse:raise TimeoutError('unknown excitation ACK')
            return '1 OK CURRENT_STEP QUEUED ONE_BATCH=1 STEPS=10 LOCKED_ACK=1'
        if cmd==b.STATUS:
            return ('1 OK CURRENT_STEP STATE=3 DONE=10 USED=1' if self.active else
                    '1 OK CURRENT_STEP STATE=0 DONE=0 USED=0')
        if cmd=='MOTOR TEST PROFILE':return '1 OK NAME=CURRENT_STEP_AB FSM=BYPASSED SPEED_PI=0 ID_REF=0 LIMIT_MA=500 MANUAL_BATCH=1'
        if cmd=='MOTOR TEST FILTER':return '1 OK FAST_REJECT=1 REPAIR=0 METHOD=TWO_SAMPLE JUMP=100 RETURN=40 CONFIRM=25 UNRESOLVED_LIMIT=3 HOLD=1'
        if cmd=='MOTOR TEST STATUS':return '1 OK STATE=1 USED=0 ZERO=3 FAULT=0 FLAGS=0 SD=0 MOE=0 CCER=0'
        if cmd=='ADC TIMING':return '1 OK MISS=0 PF=0 DWT=1'
        if cmd=='ANALOG SAFE STATUS':return '1 OK LATCHED=1 SD=0 MOE=0 FOC=0'
        return '1 OK'


class StepBoardTests(unittest.TestCase):
    def fixture(self):
        stack=ExitStack()
        stack.enter_context(patch.object(b.base,'motor_stack',return_value=dict(VALID='1',FREE_B='2520')))
        stack.enter_context(patch.object(b.base.old.prior,'checkpoint'))
        return stack

    def test_default_pins_and_no_hardware(self):
        self.assertEqual(len(b.image()),214300)
        b.configure();self.assertEqual(b.base.EXPECT_META[2:6],(2,0,0,888))
        p=subprocess.run([sys.executable,str(ROOT/'tools/current_step_ab_board.py')],capture_output=True,text=True,timeout=10)
        self.assertEqual(p.returncode,0,p.stdout+p.stderr);self.assertIn('no devices',p.stdout)

    def test_explicit_later_restore_is_full_identity_checked_files_only(self):
        receipt=ROOT/'tmp/current-step-ab-restore-1792570613506706900.json'
        with patch.object(b.base.hw,'debug') as debug,patch.object(b.base.support.support,'open_port') as serial:
            b.configure(receipt)
            self.assertEqual(b.base.EXPECT_META[2:6],(2,0,0,892))
            self.assertEqual(b.base.BASE_SHA,'d30c355fa88eea856d62d47663f64e0a27668f1dc266cfd34ab8349012417474')
            self.assertEqual(b.base.BASE_RESTORE_RECEIPT,receipt.resolve())
            with self.assertRaises(ValueError):
                b.configure(ROOT/'tmp/current-step-ab-run-1792570483711951500.json')
            debug.assert_not_called();serial.assert_not_called()
        b.configure()
        self.assertEqual(b.base.EXPECT_META[5],888)

    def test_physical_flags_required_before_any_device(self):
        with patch.object(b.base.hw,'debug') as debug,patch.object(b.base.support.support,'open_port') as serial:
            for call in (lambda:b.stage({},'unused',b''),lambda:b.execute({},'unused',ROOT/'tmp/unused.json',b''),
                         lambda:b.restore({},'unused',ROOT/'tmp/unused.json',b'')):
                with self.assertRaises(ValueError):call()
            debug.assert_not_called();serial.assert_not_called()

    def test_one_batch_no_normal_start_and_stopped_readout(self):
        board=FakeBoard();row=dict(postflight={},excitation_attempts=0)
        with self.fixture():b.motion(board,row)
        self.assertEqual(board.calls.count(b.COMMAND),1);self.assertEqual(row['excitation_attempts'],1)
        self.assertNotIn('START',board.calls)
        self.assertLess(board.calls.index('ANALOG SAFE'),board.calls.index('MOTOR TEST CURRENT STEP METRIC 0'))
        self.assertEqual(sum(x.startswith('MOTOR TEST CURRENT STEP ROW ') for x in board.calls),60)
        self.assertEqual(sum(x.startswith('MOTOR TEST CURRENT STEP METRIC ') for x in board.calls),10)

    def test_unknown_ack_closes_never_resends(self):
        board=FakeBoard(True);row=dict(postflight={})
        with self.fixture(),self.assertRaises(TimeoutError):b.motion(board,row)
        self.assertEqual(board.calls.count(b.COMMAND),1)
        self.assertIn('MOTOR TEST STOP',board.calls);self.assertIn('ANALOG SAFE',board.calls)

    def test_wrong_profile_or_readiness_blocks_excitation(self):
        for line in ('1 OK NAME=PROTECTED_PIPELINE_CLOSED_LOOP',
                     '1 OK NAME=CURRENT_STEP_AB FSM=BYPASSED SPEED_PI=1 ID_REF=0 LIMIT_MA=500 MANUAL_BATCH=1'):
            with self.assertRaises(RuntimeError):b.profile(line)
        with self.assertRaises(RuntimeError):b.ready('1 OK STATE=1 USED=0 ZERO=3 FAULT=0 FLAGS=0 SD=1 MOE=0 CCER=0')


if __name__=='__main__':unittest.main()
