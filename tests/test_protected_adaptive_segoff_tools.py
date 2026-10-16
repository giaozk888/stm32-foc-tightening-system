"""Offline identity and policy gates; never opens hardware or private files."""
import copy
import json
from pathlib import Path
import unittest
from unittest.mock import patch
import protected_adaptive_segoff_stage as profile
import protected_adaptive_baseline as baseline
from protected_adaptive_acceptance import validate_adaptive

class SegmentOffToolTests(unittest.TestCase):
    def test_exact_image_and_stage_receipt_key(self):
        self.assertEqual(len(profile.pinned_image()),206192)
        self.assertEqual(profile.BASELINE_KEY,profile.historical.runner.BASELINE_KEY)
        with patch.object(profile,'SHA','0'*64),self.assertRaises(RuntimeError): profile.pinned_image()

    def test_baseline_and_expected_fault_identity(self):
        row=dict(fw=dict(CURRENT='A',CONFIRMED='A',PENDING='-',ATTEMPTS='0',ACTIVE='0',GEN='518'),
            safe=dict(LATCHED='1',SD='0',MOE='0',FOC='0'),status='OK FLT=1',zero={'STATE':'3'},
            protection=dict(REASON='9',FLAGS='0'),fault={'SEQ':'297111'})
        baseline.identity(row,profile); profile.expected_fault(row)
        bad=copy.deepcopy(row); bad['fw']['GEN']='514'
        with self.assertRaises(RuntimeError): baseline.identity(bad,profile)
        bad=copy.deepcopy(row); bad['fault']['SEQ']='1'
        with self.assertRaises(RuntimeError): profile.expected_fault(bad)

    def test_fresh_healthy_baseline_no_bypass(self):
        r=dict(pass_=True,mode='healthy-a518',resets=1,motor_commands=0,all_flash_unchanged=True,
            powered_motor_disconnected_user_confirmed=True,original_receipt=str(profile.ORIGINAL),
            fw={'GEN':'518'},status='OK FLT=0',zero={'STATE':'3','N':'4000'},
            safe=dict(LATCHED='1',SD='0',MOE='0',FOC='0'))
        path=profile.OUTPUT/(profile.BASELINE_PREFIX+'-unit.json')
        with patch.object(profile,'original_baseline'),patch.object(
            profile.board_profile.previous,'private_capture',return_value=b'flash'):
            with patch.object(Path,'read_text',return_value=json.dumps(r)):
                self.assertEqual(profile.verified_baseline(b'flash',path),518)
            for key,value in [('resets',0),('status','OK FLT=1'),('mode','healthy-a514')]:
                with patch.object(Path,'read_text',return_value=json.dumps(dict(r,**{key:value}))),self.assertRaises(RuntimeError):
                    profile.verified_baseline(b'flash',path)

    def test_segment_off_does_not_accept_other_zero_failures(self):
        r=dict(adaptive=dict(ADAPT='1',HARD_OFF='1',DELAY_PAIRS='1',JUMP='20,40',
            NOISE_Q8='256,1024',LEARNED='100,100'),robust_zero=dict(BLOCK='5',SEGMENT='500',
            SEGMENTS='8',OUTLIERS='20',MAX='20',SEG_MAX='OFF',SEG_OUTLIERS='0',FLAGS='0',HARD_OFF='1'))
        validate_adaptive(r,'OFF')
        for key,value in [('OUTLIERS','21'),('FLAGS','8'),('SEGMENTS','7'),('SEG_MAX','3'),('SEG_OUTLIERS','1')]:
            bad=copy.deepcopy(r); bad['robust_zero'][key]=value
            with self.assertRaises(RuntimeError): validate_adaptive(bad,'OFF')

if __name__=='__main__': unittest.main()
