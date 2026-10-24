"""Exact 240rpm/500mA runner: files/default and mocked device contracts only."""
from pathlib import Path
import subprocess
import sys
import time
import unittest
from unittest.mock import Mock,patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
import rundown240_speed_board as board


class Rundown240BoardTests(unittest.TestCase):
    def test_exact_image_baseline_and_default_never_opens_devices(self):
        self.assertEqual(len(board.image()),228540)
        self.assertEqual(board.old.zero.latest_meta(board.baseline())[2:6],(2,0,0,733))
        p=subprocess.run([sys.executable,str(ROOT/'tools/rundown240_speed_board.py')],
            capture_output=True,text=True,timeout=10)
        self.assertEqual(p.returncode,0,p.stdout+p.stderr)
        self.assertIn('240rpm/500mA A and B733; no devices',p.stdout)

    def test_fresh_physical_state_before_any_device_access(self):
        with patch.object(board.hw,'debug') as debug,patch.object(board.support.support,'open_port') as serial:
            for function,args in ((board.stage,({},'unused',b'')),
                    (board.execute,({},'unused',ROOT/'tmp/unused.json',b'')),
                    (board.restore,({},'unused',ROOT/'tmp/unused.json',b''))):
                with self.assertRaises(ValueError): function(*args)
            debug.assert_not_called(); serial.assert_not_called()

    def test_old_20rpm_profile_cannot_start_new_trial(self):
        profile='OK NAME=PROTECTED_PIPELINE_CLOSED_LOOP HARD_OFF=0 FSM=ORIGINAL PIPELINE=1 LOCAL=1 '
        profile+='RPM=240 LEASE_US=12000000 CM=85 SPEED_CTRL=SB3 VLIMIT_MV=1600 ILIMIT_MV=750 QUALIFIED=0'
        self.assertEqual(board.profile(profile)['RPM'],'240')
        for wrong in (profile.replace('RPM=240','RPM=20'),profile.replace('CM=85','CM=0')):
            with self.assertRaisesRegex(RuntimeError,'no START'): board.profile(wrong)

    def test_preflight_failure_still_captures_and_never_sends_start(self):
        row=dict(powered_no_alarm=True,steps=[],commands=[]); console=Mock()
        with patch.object(board,'staged',return_value=(ROOT/'tmp/unused.bin',b'capture')), \
             patch.object(board.support.support,'open_port',return_value=Mock()), \
             patch.object(board.old.prior,'JournalConsole',return_value=console), \
             patch.object(board.hw,'debug'), \
             patch.object(board.old.prior,'wait_health_confirmation',side_effect=RuntimeError('zero fail')), \
             patch.object(board,'motion') as motion, \
             patch.object(board.old,'capture_stopped') as capture:
            with self.assertRaisesRegex(RuntimeError,'zero fail'): board.execute(row,'unused',ROOT/'tmp/unused.json',b'image')
            motion.assert_not_called(); capture.assert_called_once()

    def test_fault_stops_with_one_start_no_set_save_or_automatic_retry(self):
        class Fake:
            def __init__(self): self.sent=[]; self.commands=[]; self.ack=False; self.stack_pending=False
            def command(self,cmd,timeout=1):
                self.commands.append(cmd)
                if cmd=='MOTOR TEST STATUS': return '1 OK STATE=1 USED=0 ZERO=3 FAULT=0 FLAGS=0 SD=0 MOE=0 CCER=0'
                if cmd=='ADC TIMING': return '1 OK MISS=0 PF=0 DWT=1'
                if cmd=='GET RUNDOWN_RPM': return '1 OK RUNDOWN_RPM=240'
                if cmd.startswith('GET '): return '1 OK '+cmd[4:]+'=100'
                if cmd=='ANALOG SAFE STATUS': return '1 OK LATCHED=1 SD=0 MOE=0 FOC=0'
                return '1 OK'
            def send(self,cmd):
                self.sent.append(cmd)
                if cmd=='ENC DIAG': self.stack_pending=True; return 90
                return 101 if cmd=='START' else 102
            def read_line(self,seconds):
                if self.stack_pending: self.stack_pending=False; return '90 OK ENC STACK VALID=1 FREE_B=512'
                if not self.ack: self.ack=True; return '101 OK START QUEUED'
                if 'STATUS' in self.sent: return '102 OK STATUS FLT=1 BUSY=0 CONTACT=0 OUTCOME=FAULT'
                time.sleep(.001); return None
        fake=Fake(); row=dict(start_attempts=0,samples=[],postflight={})
        with patch.object(board,'require_idle_ready'),patch.object(board,'profile'),patch.object(board,'check_recipe'):
            with self.assertRaisesRegex(RuntimeError,'Protection fault'): board.motion(fake,row)
        self.assertEqual(fake.sent.count('START'),1)
        self.assertIn('STOP',fake.commands); self.assertIn('ANALOG SAFE',fake.commands)
        self.assertFalse(any(c.startswith(('SET ','SAVE')) for c in fake.commands))

    def test_summary_requires_sustained_tracking_not_one_speed_peak(self):
        def samples(speeds):
            return [dict(elapsed_s=i*.1,status=dict(BUSY='1',CTRL=str(v)+'rpm',POS=str(i*100)+'deg'))
                    for i,v in enumerate(speeds)]
        self.assertTrue(board.speed_summary(samples([220,230,240,245,238]))['tracking_pass'])
        self.assertFalse(board.speed_summary(samples([0,0,240,0,0]))['tracking_pass'])
        self.assertFalse(board.speed_summary([])['tracking_pass'])
        source=Path(board.__file__).read_text()
        self.assertIn('HOST_MAX_SECONDS=2.0',source)
        self.assertNotIn('SET RUNDOWN_RPM',source)
        self.assertNotIn('setattr(',source)

if __name__=='__main__': unittest.main()
