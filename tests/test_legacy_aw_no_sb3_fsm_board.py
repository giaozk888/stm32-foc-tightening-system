"""Exact 240rpm/500mA runner: files/default and mocked device contracts only."""
from pathlib import Path
import json
import zlib
import subprocess
import sys
import time
import unittest
from unittest.mock import Mock,patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
import legacy_aw_no_sb3_fsm_board as board


class LegacyAwNoSb3FsmBoardTests(unittest.TestCase):
    def test_pending_a_failure_can_only_restore_validated_b_without_confirming_a(self):
        for state in ((1,0,0),(2,1,1)):
            self.assertTrue(board.restorable_state((0,3,*state,743)))
        for state in ((1,1,1),(2,2,1),(2,1,2),(0,0,0),(2,1,0)):
            self.assertFalse(board.restorable_state((0,3,*state,743)))
        data=board.image(); base=board.baseline(); before=bytearray(base)
        before[0x8000:0x8000+len(data)]=data; before=bytes(before)
        meta=(0,3,2,1,1,743,len(data),zlib.crc32(data),227964,627317606,0,0)
        expected=board.TMP/'mock-pending-A.bin'
        receipt=dict(mode='run',image_sha256=board.SHA,elf_sha256=board.ELF_SHA,
            final_capture=str(expected),final_sha256=board.old.zero.digest(before),
            final_cpu_halted=True,final_outputs_off=True,all_app_private_unchanged=True)
        with patch.object(Path,'read_text',return_value=json.dumps(receipt)), \
             patch.object(Path,'read_bytes',return_value=before), \
             patch.object(board,'baseline',return_value=base), \
             patch.object(board.old.zero,'latest_meta',return_value=meta), \
             patch.object(board.hw,'debug',side_effect=RuntimeError('STOP_BEFORE_DEVICE')) as debug:
            with self.assertRaisesRegex(RuntimeError,'STOP_BEFORE_DEVICE'):
                board.restore(dict(physical_power_off=True),'unused',board.TMP/'mock-run.json',data)
        commands=debug.call_args.args[1]
        for command in board.hw.write_mailbox(board.mailbox(3,1,2)):
            self.assertIn(command,commands)
        entry=int.from_bytes(before[0x40004:0x40008],'little')&~1
        self.assertIn(f'bp {entry:#x} 2 hw',commands)
        self.assertIn('wait_halt 25000',commands)

    def test_exact_image_baseline_and_default_never_opens_devices(self):
        self.assertEqual(len(board.image()),228140)
        self.assertEqual(board.old.zero.latest_meta(board.baseline())[2:6],(2,0,0,760))
        p=subprocess.run([sys.executable,str(ROOT/'tools/legacy_aw_no_sb3_fsm_board.py')],
            capture_output=True,text=True,timeout=10)
        self.assertEqual(p.returncode,0,p.stdout+p.stderr)
        self.assertIn('240rpm/500mA/20000deg A and B760; no devices',p.stdout)

    def test_fresh_physical_state_before_any_device_access(self):
        with patch.object(board.hw,'debug') as debug,patch.object(board.support.support,'open_port') as serial:
            for function,args in ((board.stage,({},'unused',b'')),
                    (board.execute,({},'unused',ROOT/'tmp/unused.json',b'')),
                    (board.restore,({},'unused',ROOT/'tmp/unused.json',b''))):
                with self.assertRaises(ValueError): function(*args)
            debug.assert_not_called(); serial.assert_not_called()

    def test_old_20rpm_profile_cannot_start_new_trial(self):
        profile='OK NAME=PROTECTED_PIPELINE_CLOSED_LOOP HARD_OFF=0 FSM=ORIGINAL PIPELINE=1 LOCAL=1 '
        profile+='RPM=240 LEASE_US=12000000 CM=85 SPEED_CTRL=L00 VLIMIT_MV=1600 ILIMIT_MV=750 QUALIFIED=0'
        self.assertEqual(board.profile(profile)['RPM'],'240')
        for wrong in (profile.replace('RPM=240','RPM=20'),profile.replace('CM=85','CM=0'),profile.replace('SPEED_CTRL=L00','SPEED_CTRL=SB3'),profile.replace('SPEED_CTRL=L00','SPEED_CTRL=AW1'),profile.replace('SPEED_CTRL=L00','SPEED_CTRL=AW0')):
            with self.assertRaisesRegex(RuntimeError,'no START'): board.profile(wrong)

    def test_filter_threshold_mismatch_prevents_start(self):
        good='OK FAST_REJECT=1 REPAIR=0 METHOD=TWO_SAMPLE JUMP=100 RETURN=40 CONFIRM=25 UNRESOLVED_LIMIT=3 HOLD=1'
        self.assertEqual(board.filter_profile(good)['RETURN'],'40')
        for wrong in (good.replace('JUMP=100','JUMP=60'),good.replace('RETURN=40','RETURN=25'),
                      good.replace('CONFIRM=25','CONFIRM=40'),good.replace('UNRESOLVED_LIMIT=3','UNRESOLVED_LIMIT=4')):
            with self.assertRaisesRegex(RuntimeError,'no START'): board.filter_profile(wrong)
        fake=Mock()
        fake.command.side_effect=['ignored profile',good.replace('RETURN=40','RETURN=25'),
                                  'safe ack','OK LATCHED=1 SD=0 MOE=0 FOC=0','fault','timing','status']
        with patch.object(board,'require_idle_ready'),patch.object(board,'profile'):
            with self.assertRaisesRegex(RuntimeError,'no START'):
                board.motion(fake,dict(start_attempts=0,samples=[],postflight={}))
        fake.send.assert_not_called()

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
                if cmd=='MOTOR TEST FILTER': return '1 OK FAST_REJECT=1 REPAIR=0 METHOD=TWO_SAMPLE JUMP=100 RETURN=40 CONFIRM=25 UNRESOLVED_LIMIT=3 HOLD=1'
                if cmd=='ADC TIMING': return '1 OK MISS=0 PF=0 DWT=1'
                if cmd=='GET RUNDOWN_RPM': return '1 OK RUNDOWN_RPM=240'
                if cmd=='GET MAX_TRAVEL_DEG': return '1 OK MAX_TRAVEL_DEG=20000'
                if cmd=='GET RUNDOWN_TIMEOUT_MS': return '1 OK RUNDOWN_TIMEOUT_MS=8000'
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
        self.assertIn('HOST_MAX_SECONDS=11.95',source)
        self.assertNotIn('SET RUNDOWN_RPM',source)
        self.assertNotIn('setattr(',source)
        self.assertIn("flash write_image erase",source)
        self.assertIn("recipe['MAX_TRAVEL_DEG']!=20000",source)
        self.assertIn("row['fsm_terminal_seen']=True",source)

if __name__=='__main__': unittest.main()








