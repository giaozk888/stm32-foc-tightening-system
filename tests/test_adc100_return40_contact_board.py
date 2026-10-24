"""File identity and mocked fixed-workpiece trial contracts; no hardware."""
import json
from pathlib import Path
import subprocess
import sys
import time
import unittest
from unittest.mock import Mock,patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
import adc100_return40_contact_board as board


class FakeBoard:
    def __init__(self,fault=False):
        self.sent=[]; self.commands=[]; self.stack=False; self.ack=False
        self.t0=time.monotonic(); self.fault=fault
        self.recipe=dict(zip(board.RECIPE_NAMES,(240,10,300,250,8000,20000,
            80,100,120,150,150,300,300,300,300,500,30,90)))
    def command(self,cmd,timeout=1):
        self.commands.append(cmd)
        if cmd=='MOTOR TEST STATUS': return '1 OK STATE=1 USED=0 ZERO=3 FAULT=0 FLAGS=0 SD=0 MOE=0 CCER=0'
        if cmd=='MOTOR TEST FILTER': return '1 OK FAST_REJECT=1 REPAIR=0 METHOD=TWO_SAMPLE JUMP=100 RETURN=40 CONFIRM=25 UNRESOLVED_LIMIT=3 HOLD=1'
        if cmd=='ADC TIMING': return '1 OK MISS=0 PF=0 DWT=1'
        if cmd.startswith('GET '): return '1 OK '+cmd[4:]+'='+str(self.recipe[cmd[4:]])
        if cmd=='ANALOG SAFE STATUS': return '1 OK LATCHED=1 SD=0 MOE=0 FOC=0'
        return '1 OK'
    def send(self,cmd):
        self.sent.append(cmd)
        if cmd=='ENC DIAG': self.stack=True; return 90
        return 101 if cmd=='START' else 102
    def read_line(self,seconds):
        if self.stack: self.stack=False; return '90 OK ENC STACK VALID=1 FREE_B=512'
        if not self.ack: self.ack=True; return '101 OK START QUEUED'
        if self.sent[-1]=='STATUS':
            if self.fault: return '102 OK STATUS FLT=1 BUSY=0 CONTACT=1 OUTCOME=FAULT'
            busy='1' if time.monotonic()-self.t0<.23 else '0'
            return '102 OK STATUS FLT=0 BUSY='+busy+' CONTACT=1 OUTCOME=OK CTRL=0rpm POS=360deg'
        time.sleep(.001); return None


class ContactBoardTests(unittest.TestCase):
    def row(self):
        return dict(start_attempts=0,samples=[],postflight={},fixed_workpiece_guarded=True)

    def test_exact_files_default_opens_no_devices_and_no_programming(self):
        self.assertEqual(len(board.image()),228620)
        base=board.baseline()
        self.assertEqual(board.old.zero.latest_meta(base)[2:6],(2,0,0,748))
        self.assertEqual(base[0x8000:0x8000+228620],board.image())
        run=subprocess.run([sys.executable,str(Path(board.__file__))],capture_output=True,text=True,timeout=10)
        self.assertEqual(run.returncode,0,run.stdout+run.stderr)
        self.assertIn('B748; no devices',run.stdout)
        source=Path(board.__file__).read_text()
        self.assertNotIn('flash write_image',source)
        self.assertNotIn('SET RUNDOWN_RPM',source)
        self.assertIn('HOST_MAX_SECONDS=11.95',source)

    def test_inspect_commands_never_reset_or_program(self):
        with patch.object(board.hw,'debug',side_effect=RuntimeError('STOP_BEFORE_DEVICE')) as debug:
            with self.assertRaisesRegex(RuntimeError,'STOP_BEFORE_DEVICE'):
                board.inspect_off(dict(physical_power_off=True),'unused',board.image())
        commands=debug.call_args.args[1]
        self.assertTrue(any('verify_image' in c for c in commands))
        self.assertFalse(any('flash write' in c or c.startswith('reset') or c.startswith('resume') for c in commands))

    def test_physical_guards_before_device_or_start(self):
        with patch.object(board.hw,'debug') as debug,patch.object(board.support.support,'open_port') as port:
            with self.assertRaises(ValueError): board.inspect_off({},'unused',b'')
            with self.assertRaises(ValueError): board.execute(dict(powered_no_alarm=True),'unused',ROOT/'tmp/unused.json',b'')
            debug.assert_not_called(); port.assert_not_called()
        fake=FakeBoard()
        with self.assertRaisesRegex(ValueError,'no START'):
            board.motion(fake,dict(start_attempts=0,samples=[],postflight={}))
        self.assertNotIn('START',fake.sent)

    def test_contact_does_not_stop_cycle_but_fault_stops_with_no_retry(self):
        for fault in (False,True):
            fake=FakeBoard(fault); row=self.row()
            with patch.object(board,'require_idle_ready'),patch.object(board,'profile'):
                if fault:
                    with self.assertRaisesRegex(RuntimeError,'Protection fault'): board.motion(fake,row)
                else:
                    board.motion(fake,row)
                    self.assertTrue(row['contact_observed'])
                    self.assertTrue(row['fsm_observation_complete'])
                    self.assertEqual(row['terminal_status_request'],'102')
            self.assertEqual(fake.sent.count('START'),1)
            self.assertIn('STOP',fake.commands); self.assertIn('ANALOG SAFE',fake.commands)
            self.assertFalse(any(c.startswith(('SET ','SAVE')) for c in fake.commands))

    def test_no_fake_success_without_request_matched_done_and_motion_contact(self):
        lines=['EVT REQ=101 STARTED MODE=RUNDOWN TARGET=240rpm']
        for req,state in enumerate(('RUNDOWN_START','RUNDOWN','CONTACT_CONFIRM','TIGHTEN','HOLD'),110):
            lines.extend([f'{req} OK STATUS START_REQ=101',
                f'0 EVT FSM REQ={req} FSM_STATE={state} RUNDOWN_ARMED=1 CONTACT_CONFIRMED=1'])
        lines.extend(['EVT REQ=101 COMPLETE RESULT=OK','102 OK STATUS START_REQ=101',
            '0 EVT FSM REQ=102 FSM_STATE=IDLE PREV_STATE=DONE RUNDOWN_ARMED=0 CONTACT_CONFIRMED=0'])
        good=dict(terminal_status=dict(OUTCOME='OK',CONTACT='0',FLT='0',START_REQ='101'),
            terminal_status_request='102',start_request_id=101,uart=[dict(line=line) for line in lines])
        board.assess_contact_cycle(good)
        self.assertTrue(good['contact_cycle_pass']); self.assertFalse(good['torque_accuracy_verified'])
        for old,new in (('RUNDOWN_ARMED=1','RUNDOWN_ARMED=0'),('FSM_STATE=HOLD','FSM_STATE=IDLE'),
                ('CONTACT_CONFIRMED=1','CONTACT_CONFIRMED=0'),('REQ=102','REQ=103'),
                ('PREV_STATE=DONE','PREV_STATE=FAULT'),
                ('COMPLETE RESULT=OK','COMPLETE RESULT=TIMEOUT')):
            bad=json.loads(json.dumps(good))
            for item in bad['uart']: item['line']=item['line'].replace(old,new)
            with self.assertRaisesRegex(RuntimeError,'no retry'): board.assess_contact_cycle(bad)

    @unittest.skipUnless((ROOT/'tmp/adc100-return40-contact-run-1792462486181991600.json').exists(),
        'Local ignored real-session capture not distributed')
    def test_real_capture_completion_then_idle_flag_reset_is_offline_verifiable(self):
        row=json.loads((ROOT/'tmp/adc100-return40-contact-run-1792462486181991600.json').read_text())
        self.assertEqual(row['image_sha256'],board.SHA)
        self.assertEqual(row['start_attempts'],1)
        self.assertTrue(row['final_outputs_off']); self.assertTrue(row['final_cpu_halted'])
        self.assertEqual(row['terminal_status']['CONTACT'],'0')
        self.assertEqual(row['snapshot']['first_fault']['valid'],0)
        board.assess_contact_cycle(row)
        self.assertTrue(row['contact_cycle_pass'])

    def test_preflight_failure_captures_without_start(self):
        row=dict(powered_no_alarm=True,fixed_workpiece_guarded=True,steps=[],commands=[])
        with patch.object(board,'staged',return_value=(ROOT/'tmp/unused.bin',b'capture')), \
             patch.object(board.support.support,'open_port',return_value=Mock()), \
             patch.object(board.old.prior,'JournalConsole',return_value=Mock()), \
             patch.object(board.hw,'debug'), \
             patch.object(board.old.prior,'wait_health_confirmation',side_effect=RuntimeError('zero fail')), \
             patch.object(board,'motion') as motion,patch.object(board.old,'capture_stopped') as capture:
            with self.assertRaisesRegex(RuntimeError,'zero fail'):
                board.execute(row,'unused',ROOT/'tmp/unused.json',b'image')
            motion.assert_not_called(); capture.assert_called_once()


if __name__=='__main__': unittest.main()
