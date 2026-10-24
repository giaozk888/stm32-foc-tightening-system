import copy
import json
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch
from test_torque_chain import ROOT
sys.path.insert(0,str(ROOT/'tools'))
import startup_timestamps_board as board


class StartupBoardTests(unittest.TestCase):
    @staticmethod
    def row():
        s=dict(valid=31,t0_us=1000,t_iq_us=2000,t_motion_us=3000,t_speed_us=4000,t_stable_us=54000,
            motion_direction=1,motion_begin_us=2500,iq_at_event_a=.105,speed_at_event_rpm=2.)
        return dict(tokenized_decoded=[dict(decoded=line) for line in (
            'STT A seq=100 valid=31 t0_us=1000 tiq_us=2000',
            'STT B seq=100 tmotion_us=3000 tspeed_us=4000 tstable_us=54000',
            'STT C seq=100 motion_begin_us=2500 iq_at_event_a=0.105000',
            'STT D seq=100 motion_dir=1 speed_at_event_rpm=2.000000')],
            startup_saved=dict(snapshot=s,timings=dict(relative_to_t0=dict(t0_delay_us=0,
            t_iq_delay_us=1000,t_motion_delay_us=2000,t_speed_delay_us=3000,t_stable_delay_us=53000))),
            startup_uart=dict(VALID='31',T0_US='1000',TIQ_US='2000',TMOTION_US='3000',TSPEED_US='4000',TSTABLE_US='54000'))

    def test_same_uart_ram_and_all_events_required_without_inventing_missing(self):
        with patch.object(board.gain,'metrics',return_value={}):
            r=self.row();m=board.classify(r);self.assertEqual(m['startup_delays_ms']['t_iq_delay_us'],1.)
            for mutate in ('missing','mismatch','query_error'):
                bad=copy.deepcopy(r)
                if mutate=='missing':bad['startup_saved']['snapshot']['valid']=15
                elif mutate=='mismatch':bad['startup_uart']['TMOTION_US']='2000'
                else:bad['startup_query_error']='timeout'
                with self.assertRaises(RuntimeError):board.classify(bad)
            r['startup_saved']['snapshot']['motion_direction']=-1
            r['tokenized_decoded'][3]['decoded']='STT D seq=100 motion_dir=-1 speed_at_event_rpm=2.000000'
            self.assertEqual(board.classify(r)['motion_direction'],-1) # Evidence retained, never silently relabelled.

    def test_compressed_events_must_be_same_seq_and_match_saved_evidence(self):
        r=self.row();self.assertEqual(board.check_logs(r),100)
        r['tokenized_decoded'][1]['decoded']=r['tokenized_decoded'][1]['decoded'].replace('seq=100','seq=101')
        with self.assertRaises(RuntimeError):board.check_logs(r)
        r=self.row();r['startup_saved']['snapshot']['t_iq_us']=2100
        with self.assertRaises(RuntimeError):board.check_logs(r)

    def test_read_only_query_after_existing_single_motion_owner_and_wrong_gain_rejected(self):
        class Fake:
            def __init__(self):self.commands=[]
            def command(self,cmd):self.commands.append(cmd);return 'OK STARTUP VALID=31'
        b=Fake();r=dict(gain_percent=25,bemf_enabled=False)
        def motion(b,r):r['start_attempts']=1
        with patch.object(board.gain,'motion',side_effect=motion) as run:
            board.motion(b,r);run.assert_called_once_with(b,r)
        self.assertEqual(b.commands,['MOTOR TEST FF STARTUP'])
        with patch.object(board.gain,'motion') as run:
            with self.assertRaises(ValueError):board.motion(b,dict(gain_percent=100,bemf_enabled=False))
            run.assert_not_called()

    def test_default_is_files_only_and_confirmation_gates(self):
        p=subprocess.run([sys.executable,str(ROOT/'tools/startup_timestamps_board.py')],text=True,capture_output=True)
        self.assertEqual(p.returncode,0,p.stdout+p.stderr);self.assertIn('no devices',p.stdout)
        with patch.object(board,'setup') as setup:
            for args in (['--stage-off'],['--execute-powered','missing.json']):
                with self.assertRaises(SystemExit):board.main(args)
            setup.assert_not_called()

    def test_real_board_capture_five_events_and_compressed_uart_ram_agree(self):
        path=ROOT/'tmp/startup-times-run-1792649090621588900.json'
        row=json.loads(path.read_text())
        saved=board.startup.decode(path,board.ELF)
        self.assertEqual(saved,row['startup_saved'])
        self.assertEqual(board.check_logs(row),422)
        self.assertEqual(saved['snapshot']['valid'],31)
        self.assertEqual(saved['timings']['relative_to_t0'],dict(t0_delay_us=0,t_iq_delay_us=62939,
            t_motion_delay_us=73533,t_speed_delay_us=70938,t_stable_delay_us=340015))
        self.assertTrue(row['final_cpu_halted'] and row['final_outputs_off'] and row['all_app_private_unchanged'])


if __name__=='__main__':unittest.main()
