import copy
import json
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
import dob025_normal_fsm_board as board

class NormalFsmBoardTests(unittest.TestCase):
    def test_mixed_case_iqref_preserved_without_changing_legacy_parser(self):
        for value in ('500','-120','0'):
            line='123 OK STATUS BUSY=1 MODE=SPD CTRL=230.1rpm IqRef='+value+'mA FLT=0'
            parsed=board.status_fields(line)
            self.assertEqual(parsed['IqRef'],value+'mA')
            self.assertEqual(parsed['CTRL'],'230.1rpm')

    def test_files_only_frozen_image_actual_prior_b1103(self):
        p=subprocess.run([sys.executable,str(ROOT/'tools/dob025_normal_fsm_board.py')],cwd=ROOT,text=True,capture_output=True)
        self.assertEqual(p.returncode,0,p.stdout+p.stderr);self.assertIn('no devices',p.stdout)
        board.image();r=json.loads(board.ROOT_RESTORE.read_text())
        self.assertEqual(r['metadata'][5],1103);self.assertEqual(r['image_sha256'],board.prior.SHA)
        self.assertTrue(r['pass_'] and r['b_application_not_run'])
        self.assertEqual(board.FB_CONFIG['GAIN_PPM'],'250000')

    def test_missing_physical_gates_block_before_configure(self):
        for args in (['--stage-off'],['--execute-powered','absent'],['--execute-powered','absent',
            '--operator-present-drive-on-no-alarm-05a'],['--restore-b-drive-off','absent']):
            with patch.object(board,'configure') as configure:
                with self.assertRaises(SystemExit):board.main(args)
                configure.assert_not_called()

    def test_wrong_default_gain_blocks_without_start(self):
        class Wrong:
            def command(self,cmd):
                assert cmd=='MOTOR TEST MECH DOB FB CFG'
                return 'OK DOBFB '+ ' '.join(k+'='+v for k,v in dict(board.FB_CONFIG,GAIN_PPM='500000').items())
        with self.assertRaises(RuntimeError):board.model_checks(Wrong(),{})

    def test_contact_is_observed_not_forced_or_rejected_and_one_start(self):
        class Fake:
            def __init__(self):self.t=0;self.n=50;self.sent=[];self.queue=[];self.polls=0
            def send(self,cmd):
                self.n+=1;self.sent.append(cmd);req=self.n
                if cmd=='START':self.queue.append(f'{req} OK START QUEUED')
                elif cmd=='STATUS':
                    self.polls+=1
                    self.queue.append(f'{req} OK STATUS FLT=0 CONTACT=1 BUSY='+('1' if self.polls<4 else '0')+' OUTCOME=OK')
                elif cmd=='MOTOR TEST MECH DOB':self.queue.append(f'{req} OK DOB FEEDBACK=1 VALID=1')
                else:self.queue.append(f'{req} OK DOBFB ON=1 US=1000 COMP_UA=1000')
                return req
            def read_line(self,seconds=.02):
                self.t+=max(seconds,.01)
                return self.queue.pop(0) if self.queue else None
            def command(self,cmd,seconds=2):
                self.sent.append(cmd)
                if cmd.startswith('GET '):
                    k=cmd[4:];v={'RUNDOWN_RPM':240,'MAX_TRAVEL_DEG':20000,'RUNDOWN_TIMEOUT_MS':8000}.get(k,1)
                    return 'OK '+k+'='+str(v)
                if cmd=='MOTOR TEST STATUS':return 'OK STATE=1 USED=0 ZERO=3 FAULT=0 FLAGS=0 SD=0 MOE=0 CCER=0'
                if cmd=='ADC TIMING':return 'OK MISS=0 PF=0 DWT=1'
                if cmd=='ANALOG SAFE STATUS':return 'OK LATCHED=1 SD=0 MOE=0 FOC=0'
                if cmd=='MOTOR TEST FAULT':return 'OK VALID=0 FLAGS=0'
                return 'OK'
        fake=Fake();r=dict(guarded_brake_confirmed=True,powered_no_alarm=True,start_attempts=0,samples=[],postflight={})
        with patch.object(board,'require_idle_ready'),patch.object(board,'model_checks'),\
             patch.object(board.base,'profile'),patch.object(board.base,'filter_profile'),\
             patch.object(board.base,'motor_stack',return_value=dict(VALID='1',FREE_B='2048')),\
             patch.object(board,'check_recipe'),patch.object(board.base.old.prior,'checkpoint'),\
             patch.object(board,'stop'),patch.object(board.time,'monotonic',side_effect=lambda:fake.t):
            board.motion(fake,r)
        self.assertEqual(fake.sent.count('START'),1)
        self.assertFalse(any(c.startswith(('SET ','MOTOR TEST MECH RUN','MOTOR TEST MECH DOB FB ON')) for c in fake.sent))
        self.assertTrue(r['contact_observed'] and r['fsm_observation_complete'])
        self.assertEqual(r['start_attempts'],1);self.assertEqual(r['terminal_status']['OUTCOME'],'OK')

    def test_closure_failure_blocks_and_timeout_does_not_claim_tightening(self):
        r=dict(preflight_pass=True,start_attempts=1,fsm_observation_complete=True,final_cpu_halted=True,
            final_outputs_off=True,all_app_private_unchanged=True,outputs=dict(VTOR=0x08008000,SD=0,BDTR=0,CCER=0),
            terminal_status=dict(OUTCOME='RUNDOWN_TIMEOUT',FLT='0'),
            snapshot=dict(first_fault=dict(valid=0),cur_confirm=dict(fault=0),
                timing=dict(deadline_miss=0,actual_late_count=0,wall_max_us=34,actual_margin_min_us=14)),
            postflight={'MOTOR TEST FAULT':'OK VALID=0 FLAGS=0'},feedback_capture=dict(enabled=1,peak_a=.005,iq_comp_a=0))
        result=board.classify(r)
        self.assertTrue(result['acquisition_complete']);self.assertFalse(result['tightening_ok'])
        self.assertFalse(result['load_rejection_verified'])
        for key in ('final_cpu_halted','final_outputs_off','all_app_private_unchanged'):
            bad=copy.deepcopy(r);bad[key]=False
            with self.assertRaises(RuntimeError):board.classify(bad)
        bad=copy.deepcopy(r);bad['postflight']['MOTOR TEST FAULT']='OK VALID=1 FLAGS=32'
        with self.assertRaises(RuntimeError):board.classify(bad)
        bad=copy.deepcopy(r);bad['snapshot']['timing']['deadline_miss']=1
        with self.assertRaises(RuntimeError):board.classify(bad)
        off=copy.deepcopy(r);off['dob_feedback_requested']=False
        off['feedback_capture']=dict(enabled=0,peak_a=0,iq_comp_a=0)
        self.assertTrue(board.classify(off)['acquisition_complete'])
        off['feedback_capture']['peak_a']=.001
        with self.assertRaises(RuntimeError):board.classify(off)

    def test_idle_off_ack_and_readbacks_before_start_other_algorithms_unchanged(self):
        class Fake:
            def __init__(self):self.on=1;self.sent=[]
            def command(self,cmd):
                self.sent.append(cmd)
                if cmd=='MOTOR TEST MECH DOB FB OFF':self.on=0
                if cmd in ('MOTOR TEST MECH DOB FB CFG','MOTOR TEST MECH DOB FB OFF'):
                    return 'OK DOBFB '+' '.join(k+'='+v for k,v in dict(board.FB_CONFIG,ON=str(self.on)).items())
                if cmd=='MOTOR TEST FF STATUS':return 'OK ON=1 KA_NA_PER_RPM_S=46875 ACCEL_MAX_RPM_S=200 FF_PEAK_UA=9375 TOKENIZED=1'
                if cmd=='MOTOR TEST FRIC STATUS':return 'OK ON=1 I_UA=105000 DB_MRPM=2000 FF_ON=1 KA_NA_PER_RPM_S=46875 TOKENIZED=1'
                if cmd=='MOTOR TEST BEMF STATUS':return 'OK ON=1 CONFIGURED=1 PSI_NWB=348660 DQ_CROSS=0'
                if cmd=='MOTOR TEST MECH DOB MODEL':return 'OK '+' '.join(k+'='+v for k,v in dict(board.prior.fb.shadow.MODEL,FEEDBACK=str(self.on)).items())
                if cmd=='MOTOR TEST MECH DOB':return 'OK FEEDBACK='+str(self.on)+' LIVE=0 VALID=0'
                if cmd=='MOTOR TEST MECH DOB FB STATUS':return 'OK ON='+str(self.on)+' COMP_UA=0'
                if cmd=='MOTOR TEST MECH DOB ADMIT CFG':return 'OK V=5 MODE=PREFILTER JUMP_UA=200000 CONFIRM=3 ID_MAX_UA=60000 ID_US=20000 GAP_US=10000 LATCH=0 FEEDBACK='+str(self.on)
                raise AssertionError(cmd)
        f=Fake();r=dict(dob_feedback_requested=False);board.model_checks(f,r)
        self.assertEqual(r['dob_feedback_initial']['ON'],'1')
        self.assertEqual(r['dob_feedback_config']['ON'],'0')
        self.assertEqual(f.sent.count('MOTOR TEST MECH DOB FB OFF'),1)
        self.assertEqual(f.sent[:3],['MOTOR TEST MECH DOB FB CFG','MOTOR TEST MECH DOB FB OFF','MOTOR TEST MECH DOB FB CFG'])
        self.assertFalse(any(c.startswith(('START','SET ','MOTOR TEST MECH DOB FB ON')) for c in f.sent))
        self.assertTrue(all(r[k]['ON']=='1' for k in ('ff_before_start','fric_before_start','bemf_before_start')))

if __name__=='__main__':unittest.main()
