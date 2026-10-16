import json
from pathlib import Path
from unittest.mock import patch
import unittest
import protected_guard_fast_stage as stage
import protected_guard_fast_acceptance as accept
import protected_guard_fast_rollback_observe as observe


class GuardFastAcceptanceTests(unittest.TestCase):
    def test_exact_new_image_and_no_motor_or_confirmation_bypass(self):
        self.assertEqual(len(stage.pinned_image()),204824)
        self.assertNotEqual(stage.SHA,stage.previous.SHA)
        self.assertTrue(stage.REQUIRE_COST and stage.REQUIRE_LATE)
        class Port:
            def write(self,_): raise AssertionError('No writes')
        uart=accept.acceptance.TimingConsole(Port())
        for cmd in ('START','MOTOR TEST SPEED','FW CONFIRM','BOOT A','CLEAR'):
            with self.assertRaises(ValueError): uart.query(cmd)
        with self.assertRaises(RuntimeError): stage.verified_baseline(b'',Path('wrong.json'))

    def test_current_full_rollback_bytes_and_generation_are_bound(self):
        # Unit tests do not open secret-bearing Flash backups. Deployment
        # performs the real byte comparison with the restricted capture.
        raw=bytes(0x80000)
        with patch.object(stage.board_profile.previous,'private_capture',return_value=raw), \
             patch.object(stage,'latest_meta',return_value=(0,0,1,0,0,502,0,0,0,0)) as meta:
            self.assertEqual(stage.verified_baseline(raw,stage.FAILURE),502)
            with self.assertRaises(RuntimeError): stage.verified_baseline(b'1'+raw[1:],stage.FAILURE)
            meta.return_value=(0,0,1,0,0,498,0,0,0,0)
            with self.assertRaises(RuntimeError): stage.verified_baseline(raw,stage.FAILURE)

    def test_receipt_rejects_other_trial_and_missing_output_lock(self):
        failed=json.loads(stage.FAILURE.read_text('utf-8'))
        rollback=json.loads(stage.ROLLBACK.read_text('utf-8'))
        for key,value in (('image_sha256','wrong'),('host_trial_commits',2),
                          ('host_motor_commands',1),('final_outputs_off',False),
                          ('cleanup_failure','error')):
            bad=failed.copy(); bad[key]=value
            with patch.object(Path,'read_text',side_effect=[json.dumps(bad),json.dumps(rollback)]):
                with self.assertRaises(RuntimeError): stage.verified_baseline(b'',stage.FAILURE)

    def test_same_frame_late_is_failure_not_subtracted_preemption(self):
        accept.validate_late({'late_frame':dict(PATH='PAIR2',VALID='0',SEQ='0',US='0',
            PAIR_US='0',MATH_US='0',WALL_CYC='0',IRQ_CYC='0')})
        failed=json.loads(stage.FAILURE.read_text('utf-8'))
        with self.assertRaises(RuntimeError): accept.validate_late(failed['startup_sample'])

    def test_rollback_requires_exact_failure_and_no_cleanup_error(self):
        failed=json.loads(observe.FAILURE.read_text('utf-8'))
        observe.validate_failure(failed)
        for key,value in (('image_sha256','wrong'),('host_trial_commits',2),
                          ('host_motor_commands',1),('final_outputs_off',False),
                          ('cleanup_failure','error')):
            bad=failed.copy(); bad[key]=value
            with self.assertRaises(RuntimeError): observe.validate_failure(bad)

    def test_rollback_flash_and_metadata_invalidation(self):
        raw=bytes(0x80000)
        prior=(0,0,1,0,0,502,123,456,0,0)
        current=(0,0,1,0,0,506,123,456,0,0)
        with patch.object(observe,'latest_meta',side_effect=[prior,current]):
            observe.validate_flash(raw,raw,{'GEN':'506'})
        with self.assertRaises(RuntimeError):
            observe.validate_flash(raw,b'1'+raw[1:],{'GEN':'506'})
        for meta in ((0,0,1,0,0,506,123,456,789,999),
                     (0,0,2,0,0,506,123,456,0,0),
                     (0,0,1,0,0,506,999,456,0,0)):
            with patch.object(observe,'latest_meta',side_effect=[prior,meta]):
                with self.assertRaises(RuntimeError): observe.validate_flash(raw,raw,{'GEN':'506'})

    def test_old_fallback_unknown_query_keeps_off_bytes_proof_but_fails_health(self):
        raw=bytes(0x80000); written=[]
        class Port:
            def close(self): pass
        class Console:
            lines=[]
            def __init__(self,_): pass
            def query(self,cmd):
                if cmd=='MOTOR TEST STATUS': raise RuntimeError('1 ERR 100 UNKNOWN_COMMAND')
                if cmd=='STATUS': return '1 OK FLT=1'
                if cmd=='ANALOG SAFE STATUS': return '1 OK LATCHED=1 SD=0 MOE=0 FOC=0'
                return '1 OK'
        class Board:
            def __init__(self,*_): pass
            def outputs(self,*_): return {'off':'proved'}
            def capture(self,*_): return raw
        def save(path,text,**kwargs):
            written.append(json.loads(text)); return len(text)
        with patch.object(observe.profile,'Board',Board), \
             patch.object(observe.profile,'open_port',return_value=Port()), \
             patch.object(observe,'TimingConsole',Console), \
             patch.object(observe,'require_confirmed',return_value={'GEN':'506'}), \
             patch.object(observe.profile.board_profile.previous,'private_capture',return_value=raw), \
             patch.object(observe,'latest_meta',side_effect=[
                 (0,0,1,0,0,502,123,456,0,0),(0,0,1,0,0,506,123,456,0,0)]), \
             patch.object(Path,'write_text',autospec=True,side_effect=save), \
             patch('builtins.print'):
            with self.assertRaisesRegex(RuntimeError,'health failed'): observe.main()
        row=written[0]
        self.assertFalse(row['pass_'])
        self.assertTrue(row['all_app_and_private_bytes_unchanged'])
        self.assertTrue(row['failed_b_not_bootable_without_new_staging'])
        self.assertIn('UNKNOWN_COMMAND',row['fallback_diagnostics_unavailable'])
        self.assertEqual((row['motor_commands'],row['resets']),(0,0))


if __name__=='__main__': unittest.main()
