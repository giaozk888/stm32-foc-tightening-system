"""Pinned runner gates and one-shot fault exit, devices mocked."""
import subprocess
import sys
import time
import unittest
from pathlib import Path
from unittest.mock import Mock,patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
import common_mode_fsm_board as board


class CommonModeBoardTests(unittest.TestCase):
    def test_exact_files_and_default_no_device(self):
        self.assertEqual(len(board.image()),229308)
        self.assertEqual(board.old.zero.latest_meta(board.baseline())[2:6],(2,0,0,729))
        p=subprocess.run([sys.executable,str(ROOT/'tools/common_mode_fsm_board.py')],capture_output=True,text=True)
        self.assertEqual(p.returncode,0,p.stdout+p.stderr)
        self.assertIn('no devices',p.stdout)

    def test_fresh_state_gate_before_devices(self):
        with patch.object(board.hw,'debug') as debug,patch.object(board.support.support,'open_port') as serial:
            for function,args in ((board.stage,({},'unused',b'')),
                    (board.execute,({},'unused',ROOT/'tmp/unused.json',b'')),
                    (board.restore,({},'unused',ROOT/'tmp/unused.json',b''))):
                with self.assertRaises(ValueError): function(*args)
            debug.assert_not_called(); serial.assert_not_called()

    def test_missing_common_mode_identity_cannot_start(self):
        with patch.object(board,'check_profile'):
            with self.assertRaisesRegex(RuntimeError,'marker absent'): board.profile('1 OK MOTOR TEST PROFILE')

    def test_preflight_failure_no_motion_and_always_capture(self):
        row=dict(powered_no_alarm=True,steps=[],commands=[]); console=Mock()
        with patch.object(board,'staged',return_value=(ROOT/'tmp/unused.bin',b'capture')), \
             patch.object(board.support.support,'open_port',return_value=Mock()), \
             patch.object(board.old.prior,'JournalConsole',return_value=console), \
             patch.object(board.hw,'debug'), \
             patch.object(board.old.prior,'wait_health_confirmation',side_effect=RuntimeError('zero fail')), \
             patch.object(board,'motion') as motion, \
             patch.object(board.old,'capture_stopped') as capture:
            with self.assertRaisesRegex(RuntimeError,'zero fail'):
                board.execute(row,'unused',ROOT/'tmp/unused.json',b'image')
            motion.assert_not_called(); capture.assert_called_once()

    def test_runtime_fault_stops_without_second_start_or_recipe_save(self):
        class Fake:
            rpm=70
            sent=[]
            commands=[]
            ack=False
            stack_pending=False
            def command(self,cmd,timeout=1):
                self.commands.append(cmd)
                if cmd=='MOTOR TEST STATUS': return '1 OK STATE=1 USED=0 ZERO=3 FAULT=0 FLAGS=0 SD=0 MOE=0 CCER=0'
                if cmd=='ADC TIMING': return '1 OK MISS=0 PF=0 DWT=1'
                if cmd=='ENC STACK': raise AssertionError('No standalone ENC STACK protocol')
                if cmd=='GET RUNDOWN_RPM': return '1 OK RUNDOWN_RPM='+str(self.rpm)
                if cmd.startswith('GET '): return '1 OK '+cmd[4:]+'=100'
                if cmd.startswith('SET RUNDOWN_RPM '): self.rpm=int(cmd.split()[-1])
                if cmd=='ANALOG SAFE STATUS': return '1 OK LATCHED=1 SD=0 MOE=0 FOC=0'
                return '1 OK'
            def send(self,cmd):
                self.sent.append(cmd)
                if cmd=='ENC DIAG': self.stack_pending=True; return 90
                return 101 if cmd=='START' else 102
            def read_line(self,seconds):
                if self.stack_pending:
                    self.stack_pending=False; return '90 OK ENC STACK VALID=1 FREE_B=512'
                if not self.ack:
                    self.ack=True; return '101 OK START QUEUED'
                if 'STATUS' in self.sent:
                    return '102 OK STATUS FLT=1 BUSY=0 CONTACT=0 OUTCOME=FAULT'
                time.sleep(.001); return None
        fake=Fake(); row=dict(start_attempts=0,samples=[],postflight={})
        with patch.object(board,'require_idle_ready'),patch.object(board,'profile'),patch.object(board,'check_recipe'):
            with self.assertRaisesRegex(RuntimeError,'Protection fault'): board.motion(fake,row)
        self.assertEqual(fake.sent.count('START'),1)
        self.assertIn('STOP',fake.commands)
        self.assertIn('ANALOG SAFE',fake.commands)
        self.assertTrue(row['recipe_restored'])
        self.assertEqual(fake.rpm,70)
        self.assertFalse(any(c=='SAVE' for c in fake.commands))


if __name__=='__main__': unittest.main()
