"""Offline tool gates only. Never reads private bytes or opens real hardware."""
import copy
import json
from pathlib import Path
import unittest
from unittest.mock import patch
import protected_adaptive_stage as profile
import protected_adaptive_baseline as baseline
import protected_adaptive_acceptance as acceptance

class AdaptiveToolTests(unittest.TestCase):
    def test_stage_receipt_key_matches_reused_runner(self):
        self.assertEqual(profile.BASELINE_KEY,profile.runner.BASELINE_KEY)

    def test_image_identity_pinned_and_mismatch_denied(self):
        self.assertEqual(len(profile.pinned_image()),206192)
        with patch.object(profile,'SHA','0'*64),self.assertRaises(RuntimeError):
            profile.pinned_image()

    def test_board_cannot_reset_or_write(self):
        board=profile.Board({'steps':[]},'unit')
        for cmd in ('-w','-d','-e','-rst','-ob'):
            with self.assertRaises(ValueError): board.cli(cmd)

    def test_original_receipt_is_exact_not_an_arbitrary_fault_clear(self):
        r=json.loads(profile.ORIGINAL.read_text('utf-8'))
        meta=(0,0,1,0,0,514,0,0,0,0)
        with patch.object(profile,'latest_meta',return_value=meta),patch.object(
                profile.board_profile.previous,'private_capture',return_value=b'flash'):
            profile.original_baseline(b'flash')
            with self.assertRaises(RuntimeError): profile.original_baseline(b'wrong')
            bad=copy.deepcopy(r); bad['fw']['GEN']='510'
            with patch.object(Path,'read_text',return_value=json.dumps(bad)),self.assertRaises(RuntimeError):
                profile.original_baseline(b'flash')

    def test_fresh_baseline_cannot_bypass_lock_or_health(self):
        r=dict(pass_=True,mode='healthy-a514',resets=1,motor_commands=0,all_flash_unchanged=True,
            powered_motor_disconnected_user_confirmed=True,original_receipt=str(profile.ORIGINAL),
            fw={'GEN':'514'},status='OK FLT=0',zero={'STATE':'3','N':'4000'},
            safe={'LATCHED':'1','SD':'0','MOE':'0','FOC':'0'})
        path=profile.OUTPUT/'adaptive-baseline-unit.json'
        with patch.object(profile,'original_baseline') as original,patch.object(
                profile.board_profile.previous,'private_capture',return_value=b'flash'):
            with patch.object(Path,'read_text',return_value=json.dumps(r)):
                self.assertEqual(profile.verified_baseline(b'flash',path),514)
            self.assertEqual(original.call_count,1)
            for key,value in [('mode','inspect'),('resets',0),('motor_commands',1),
                    ('status','OK FLT=1'),('safe',dict(r['safe'],SD='1'))]:
                bad=dict(r); bad[key]=value
                with patch.object(Path,'read_text',return_value=json.dumps(bad)),self.assertRaises(RuntimeError):
                    profile.verified_baseline(b'flash',path)

    def test_baseline_console_refuses_motion_and_clear(self):
        class Port:
            def write(self,text): raise AssertionError('No hardware write expected')
        for cls in (baseline.Console,acceptance.AdaptiveConsole):
            uart=cls(Port())
            for cmd in ('MOTOR TEST SPEED','START','BOOT A','FW CLEAR','RESET','SET IQ 1'):
                with self.assertRaises(ValueError): uart.query(cmd)

    def test_adaptive_validation_includes_robust_failure(self):
        row=dict(adaptive=dict(ADAPT='1',HARD_OFF='1',DELAY_PAIRS='1',JUMP='20,40',
            NOISE_Q8='256,1707',LEARNED='0,100'),robust_zero=dict(BLOCK='5',SEGMENT='500',
            SEGMENTS='8',MAX='20',SEG_MAX='3',FLAGS='0',HARD_OFF='1',OUTLIERS='20'))
        acceptance.validate_adaptive(row)
        for key,value in [('FLAGS','16'),('SEGMENTS','7'),('OUTLIERS','21')]:
            bad=copy.deepcopy(row); bad['robust_zero'][key]=value
            with self.assertRaises(RuntimeError): acceptance.validate_adaptive(bad)

    def test_baseline_identity_requires_confirmed_locked_a514(self):
        row=dict(fw=dict(CURRENT='A',CONFIRMED='A',PENDING='-',ATTEMPTS='0',ACTIVE='0',GEN='514'),
            safe=dict(LATCHED='1',SD='0',MOE='0',FOC='0'))
        baseline.identity(row)
        bad=copy.deepcopy(row); bad['fw']['CURRENT']='B'
        with self.assertRaises(RuntimeError): baseline.identity(bad)

if __name__=='__main__': unittest.main()
