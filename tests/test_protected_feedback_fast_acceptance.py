import json
from pathlib import Path
import unittest
from unittest.mock import patch

import protected_feedback_fast_stage as stage
import protected_feedback_fast_acceptance as accept
import protected_feedback_fast_baseline as recovery
import protected_feedback_fast_rollback_observe as observe


class FeedbackFastAcceptanceTests(unittest.TestCase):
    def receipt(self):
        return dict(pass_=True,mode='healthy-a506',resets=1,motor_commands=0,
            all_flash_unchanged=True,powered_motor_disconnected_user_confirmed=True,
            original_receipt=str(stage.ORIGINAL),fw={'GEN':'506'},
            status='1 OK FLT=0 MODE=IDLE',zero={'STATE':'3','N':'4000'},
            safe=dict(LATCHED='1',SD='0',MOE='0',FOC='0'))

    def test_new_image_pinned_separately(self):
        self.assertEqual(len(stage.pinned_image()),205264)
        self.assertNotEqual(stage.SHA,stage.previous.SHA)
        self.assertTrue(stage.REQUIRE_COST and stage.REQUIRE_LATE)

    def test_baseline_requires_healthy_calibrated_a506(self):
        raw=bytes(0x80000); path=stage.OUTPUT/'feedback-fast-baseline-test.json'
        row=self.receipt()
        with patch.object(Path,'read_text',return_value=json.dumps(row)), \
             patch.object(stage.board_profile.previous,'private_capture',return_value=raw), \
             patch.object(stage,'original_baseline'):
            self.assertEqual(stage.verified_baseline(raw,path),506)
            with self.assertRaises(RuntimeError): stage.verified_baseline(b'1'+raw[1:],path)
        for key,value in (('pass_',False),('resets',2),('motor_commands',1),
                          ('all_flash_unchanged',False),('status','1 OK FLT=1'),
                          ('fw',{'GEN':'502'}),('zero',{'STATE':'4','N':'4000'}),
                          ('safe',dict(LATCHED='1',SD='1',MOE='0',FOC='0')),
                          ('powered_motor_disconnected_user_confirmed',False)):
            bad=row.copy(); bad[key]=value
            with patch.object(Path,'read_text',return_value=json.dumps(bad)):
                with self.assertRaises(RuntimeError): stage.verified_baseline(raw,path)

    def test_recovery_cannot_bypass_failed_rollback_identity(self):
        raw=bytes(0x80000)
        old=json.loads(stage.ORIGINAL.read_text('utf-8'))
        with patch.object(stage.board_profile.previous,'private_capture',return_value=raw), \
             patch.object(stage,'latest_meta',return_value=(0,0,1,0,0,506,123,456,0,0)):
            stage.original_baseline(raw)
            with self.assertRaises(RuntimeError): stage.original_baseline(b'1'+raw[1:])
        for key,value in (('all_app_and_private_bytes_unchanged',False),('resets',1),
                          ('fallback_fault',False),('image_sha256','wrong')):
            bad=old.copy(); bad[key]=value
            with patch.object(Path,'read_text',return_value=json.dumps(bad)):
                with self.assertRaises(RuntimeError): stage.original_baseline(raw)

    def test_commands_cannot_activate_motor_clear_or_force_confirm(self):
        class Port:
            def write(self,_): raise AssertionError('No command should reach UART')
        for cls in (recovery.Console,accept.acceptance.TimingConsole):
            u=cls(Port())
            for cmd in ('START','MOTOR TEST SPEED','CLEAR','BOOT A','FW CONFIRM'):
                with self.assertRaises(ValueError): u.query(cmd)
        for cmd in ('FW END','BENCH RUN','BENCH PROTECTION TEST TIMEOUT'):
            with self.assertRaises(ValueError): recovery.Console(Port()).query(cmd)

    def test_same_frame_wall_time_not_cpu_time_is_acceptance(self):
        failed=json.loads(stage.previous.OUTPUT.joinpath(
            'irq-compute-1791977292041516100.json').read_text('utf-8'))
        with self.assertRaises(RuntimeError): accept.validate_late(failed['startup_sample'])
        self.assertEqual(failed['startup_sample']['timing']['MAX_US'],'53')

    def test_actual_feedback_inline_failure_remains_failure(self):
        failed=json.loads(stage.OUTPUT.joinpath(
            'irq-compute-1791979438472244200.json').read_text('utf-8'))
        observe.validate_failure(failed)
        sample=failed['startup_sample']
        self.assertEqual(sample['state']['FLAGS'],'256')
        self.assertEqual(sample['timing']['MAX_US'],'55')
        self.assertEqual(sample['late_frame']['US'],'55')
        self.assertLess((int(sample['late_frame']['WALL_CYC'])-
                         int(sample['late_frame']['IRQ_CYC']))/170.0,50)
        with self.assertRaises(RuntimeError): accept.validate_late(sample)

    def test_rollback_requires_single_stopped_unconfirmed_new_trial(self):
        row=dict(pass_=False,image_sha256=stage.SHA,host_trial_commits=1,
                 host_motor_commands=0,final_outputs_off=True,failure='Startup fault')
        observe.validate_failure(row)
        for key,value in (('pass_',True),('image_sha256',stage.previous.SHA),
                          ('host_trial_commits',2),('host_motor_commands',1),
                          ('cleanup_failure','error'),('confirmed',{'CURRENT':'B'})):
            bad=row.copy(); bad[key]=value
            with self.assertRaises(RuntimeError): observe.validate_failure(bad)

    def test_exact_rollback_generation_and_all_protected_bytes(self):
        raw=bytes(0x80000)
        before=(0,0,1,0,0,506,123,456,0,0)
        after=(0,0,1,0,0,510,123,456,0,0)
        with patch.object(observe,'latest_meta',side_effect=[before,after]):
            observe.validate_flash(raw,raw,{'GEN':'510'})
        for meta in ((0,0,2,0,0,510,123,456,0,0),
                     (0,0,1,0,0,510,123,456,10,20),
                     (0,0,1,0,0,506,123,456,0,0)):
            with patch.object(observe,'latest_meta',side_effect=[before,meta]):
                with self.assertRaises(RuntimeError): observe.validate_flash(raw,raw,{'GEN':'510'})
        with self.assertRaises(RuntimeError):
            observe.validate_flash(raw,b'1'+raw[1:],{'GEN':'510'})


if __name__=='__main__': unittest.main()
