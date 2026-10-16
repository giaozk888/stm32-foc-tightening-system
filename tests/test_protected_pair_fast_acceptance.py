import json
from pathlib import Path
from unittest.mock import patch
import unittest
import protected_pair_fast_stage as stage
import protected_pair_fast_acceptance as accept
import protected_pair_fast_rollback_observe as observe


class PairFastAcceptanceTests(unittest.TestCase):
    def test_pinned_image_and_no_motion_or_forced_confirmation(self):
        self.assertEqual(len(stage.pinned_image()),204792)
        self.assertTrue(stage.REQUIRE_COST and stage.REQUIRE_LATE)
        class Port:
            def write(self,_): raise AssertionError('No writes')
        uart=accept.acceptance.TimingConsole(Port())
        for cmd in ('START','MOTOR TEST SPEED','MOTOR TEST STOP','FW CONFIRM','BOOT A','CLEAR'):
            with self.assertRaises(ValueError): uart.query(cmd)
        with self.assertRaises(RuntimeError): stage.verified_baseline(b'',Path('wrong.json'))
    def test_late_record_fails_even_if_other_maxima_look_healthy(self):
        late=dict(PATH='PAIR2',VALID='0',SEQ='0',US='0',PAIR_US='0',MATH_US='0',WALL_CYC='0',IRQ_CYC='0')
        accept.validate_late({'late_frame':late})
        with self.assertRaises(RuntimeError): accept.validate_late({})
        for key,value in (('VALID','1'),('PATH','OLD'),('IRQ_CYC','-1'),('US','4294967296')):
            bad=late.copy(); bad[key]=value
            with self.assertRaises(RuntimeError): accept.validate_late({'late_frame':bad})
    def test_exact_full_rollback_baseline_and_generation(self):
        failed=dict(pass_=False,image_sha256=stage.previous.SHA,host_trial_commits=1,
                    host_motor_commands=0,failure='Startup fault; no reset/activation retry',
                    startup_sample={'state':{'FLAGS':'256'},'timing':{'MAX_US':'65'}},final_outputs_off=True)
        rollback=dict(pass_=True,image_sha256=stage.previous.SHA,motor_commands=0,resets=0,
                      all_app_and_private_bytes_unchanged=True,failed_b_not_bootable_without_new_staging=True,
                      failure_receipt=str(stage.FAILURE),fw={'GEN':'498'})
        raw=bytes(0x80000)
        with patch.object(Path,'read_text',side_effect=[json.dumps(failed),json.dumps(rollback)]*3), \
             patch.object(stage.previous.previous.trace.old.previous,'private_capture',return_value=raw), \
             patch.object(stage,'latest_meta',return_value=(0,0,1,0,0,498,0,0,0,0)) as meta:
            self.assertEqual(stage.verified_baseline(raw,stage.FAILURE),498)
            with self.assertRaises(RuntimeError): stage.verified_baseline(b'1'+raw[1:],stage.FAILURE)
            meta.return_value=(0,0,1,0,0,494,0,0,0,0)
            with self.assertRaises(RuntimeError): stage.verified_baseline(raw,stage.FAILURE)
    def test_failure_sample_collects_late_before_validation(self):
        class Uart:
            def __init__(self): self.queries=[]
            def query(self,cmd):
                self.queries.append(cmd)
                if cmd=='MOTOR TEST LATE': return '1 OK MOTOR TEST LATE PATH=PAIR2 VALID=1 SEQ=2 US=65'
                return '1 OK STATE=4 FLAGS=256'
            def encoder_diag(self): return {'dma':{'TIMEOUT':'0'}}
        uart=Uart()
        with patch.object(accept.acceptance,'profile',stage): row=accept.acceptance.read_sample(uart)
        self.assertEqual(row['late_frame']['US'],'65')
        self.assertIn('MOTOR TEST COST',uart.queries)
        with self.assertRaises(RuntimeError): accept.validate_late(row)
    def test_rollback_observer_exact_failure_binding(self):
        failed=dict(pass_=False,image_sha256=stage.SHA,host_trial_commits=1,
                    host_motor_commands=0,final_outputs_off=True,
                    startup_sample={'state':{'FLAGS':'256'},'late_frame':{'VALID':'1'}})
        observe.validate_failure(failed)
        for key,value in (('image_sha256','wrong'),('host_trial_commits',2),
                          ('host_motor_commands',1),('final_outputs_off',False),
                          ('cleanup_failure','error')):
            bad=failed.copy(); bad[key]=value
            with self.assertRaises(RuntimeError): observe.validate_failure(bad)
    def test_rollback_observer_preserves_flash_and_invalidates_failed_b(self):
        raw=bytes(0x80000)
        prior=(0,0,1,0,0,498,123,456,789,999)
        current=(0,0,1,0,0,502,123,456,0,0)
        with patch.object(observe,'latest_meta',side_effect=[prior,current]):
            observe.validate_flash(raw,raw,{'GEN':'502'})
        with self.assertRaises(RuntimeError):
            observe.validate_flash(raw,b'1'+raw[1:],{'GEN':'502'})
        for meta in ((0,0,1,0,0,502,123,456,789,999),
                     (0,0,2,0,0,502,123,456,0,0),
                     (0,0,1,0,0,502,999,456,0,0)):
            with patch.object(observe,'latest_meta',side_effect=[prior,meta]):
                with self.assertRaises(RuntimeError): observe.validate_flash(raw,raw,{'GEN':'502'})


if __name__=='__main__': unittest.main()
