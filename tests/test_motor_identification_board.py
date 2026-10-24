"""Host transport tests only: RS50 single-command/order/gates, no hardware."""
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
import motor_identification_board as b


class FakeBoard:
    def __init__(self,refuse=False):self.calls=[];self.active=False;self.refuse=refuse
    def command(self,cmd,*args):
        self.calls.append(cmd)
        if cmd==b.COMMAND:
            self.active=True
            if self.refuse:raise TimeoutError('unknown ACK, never resend')
            return '1 OK IDENT QUEUED ONE_SHOT=1 LOCKED_ACK=1'
        if cmd=='MOTOR TEST IDENT STATUS':
            return ('1 OK IDENT MODE=1 STATUS=3 REASON=0 N=32 USED=1 IMAX_MA=200 VMAX_MV=200' if self.active else
                '1 OK IDENT MODE=0 STATUS=0 REASON=0 N=0 USED=0 IMAX_MA=200 VMAX_MV=200')
        if cmd=='MOTOR TEST STATUS':return '1 OK STATE=1 USED=0 ZERO=3 FAULT=0 FLAGS=0 SD=0 MOE=0 CCER=0'
        if cmd=='ADC TIMING':return '1 OK MISS=0 PF=0 DWT=1'
        if cmd=='ANALOG SAFE STATUS':return '1 OK LATCHED=1 SD=0 MOE=0 FOC=0'
        return '1 OK'


class IdentBoardTests(unittest.TestCase):
    def test_pinned_files_baseline_no_device_default(self):
        self.assertEqual(len(b.image()),212732)
        with patch.dict(b.base.__dict__,{}):
            b.configure()
            self.assertEqual(b.base.EXPECT_META[2:6],(2,0,0,804))
            self.assertEqual(b.base.old.zero.digest(b.base.baseline()),b.BASE_SHA)
        p=subprocess.run([sys.executable,str(ROOT/'tools/motor_identification_board.py')],
            capture_output=True,text=True,timeout=10)
        self.assertEqual(p.returncode,0,p.stdout+p.stderr)
        self.assertIn('no devices',p.stdout)

    def motion_patches(self):
        from contextlib import ExitStack
        stack=ExitStack()
        for name in ('require_idle_ready','profile','filter_profile'):
            stack.enter_context(patch.object(b.base,name))
        stack.enter_context(patch.object(b.base,'motor_stack',return_value={'VALID':'1','FREE_B':'2520'}))
        stack.enter_context(patch.object(b.base.old.prior,'checkpoint'))
        return stack

    def test_only_one_explicit_rs50_and_output_off_before_trace(self):
        board=FakeBoard();row={'postflight':{}}
        with self.motion_patches():b.motion(board,row)
        self.assertEqual(board.calls.count(b.COMMAND),1)
        self.assertEqual(row['excitation_attempts'],1)
        self.assertNotIn('START',board.calls)
        self.assertLess(board.calls.index('ANALOG SAFE'),board.calls.index('MOTOR TEST IDENT ROW 0'))
        self.assertEqual(sum(x.startswith('MOTOR TEST IDENT ROW ') for x in board.calls),32)
        self.assertFalse(any('RS 75' in x or 'IDENT LD' in x or 'IDENT LQ' in x for x in board.calls))

    def test_unknown_ack_closes_and_never_retries(self):
        board=FakeBoard(True);row={'postflight':{}}
        with self.motion_patches(),self.assertRaises(TimeoutError):b.motion(board,row)
        self.assertEqual(board.calls.count(b.COMMAND),1)
        self.assertIn('MOTOR TEST STOP',board.calls);self.assertIn('ANALOG SAFE',board.calls)

    def test_missing_physical_state_blocks_all_device_calls(self):
        with patch.object(b.base.hw,'debug') as debug,patch.object(b.base.support.support,'open_port') as port:
            with self.assertRaises(ValueError):b.execute({},'unused',ROOT/'tmp/unused.json',b'')
            with self.assertRaises(ValueError):b.base.stage({},'unused',b'')
            with self.assertRaises(ValueError):b.base.restore({},'unused',ROOT/'tmp/unused.json',b'')
            debug.assert_not_called();port.assert_not_called()
        for line in ('OK MODE=1 STATUS=3 REASON=0 N=32 USED=1 IMAX_MA=200 VMAX_MV=200',
                     'OK MODE=0 STATUS=0 REASON=0 N=0 USED=0 IMAX_MA=500 VMAX_MV=200'):
            with self.assertRaises(RuntimeError):b.ready_ident(line)


if __name__=='__main__':unittest.main()
