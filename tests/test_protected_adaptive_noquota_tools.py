"""Offline-only identity and diagnostic gates; never opens serial/SWD."""
import copy
import json
from pathlib import Path
import unittest
from unittest.mock import patch

import protected_adaptive_noquota_stage as profile
from protected_adaptive_acceptance import validate_adaptive


class NoQuotaToolTests(unittest.TestCase):
    def test_exact_hard_off_b_is_pinned(self):
        self.assertEqual(len(profile.pinned_image()),206184)
        with patch.object(profile,'SHA','0'*64),self.assertRaises(RuntimeError):
            profile.pinned_image()

    def test_exact_a522_fallback_required(self):
        receipt=dict(pass_=True,image_sha256=profile.previous.SHA,resets=0,
            motor_commands=0,fallback_healthy=True,
            all_app_and_private_bytes_unchanged=True,
            failed_b_not_bootable_without_new_staging=True,fw={'GEN':'522'})
        meta=(0,0,1,0,0,522,0,0,0,0)
        with patch.object(Path,'read_text',return_value=json.dumps(receipt)),\
             patch.object(profile,'latest_meta',return_value=meta),\
             patch.object(profile.previous.board_profile.previous,'private_capture',return_value=b'flash'):
            self.assertEqual(profile.verified_baseline(b'flash',profile.ORIGINAL),522)
            bad=dict(receipt,fw={'GEN':'518'})
            with patch.object(Path,'read_text',return_value=json.dumps(bad)),\
                 self.assertRaises(RuntimeError):
                profile.verified_baseline(b'flash',profile.ORIGINAL)
        with self.assertRaises(RuntimeError):
            profile.verified_baseline(b'flash',profile.OUTPUT/'other.json')

    def test_no_quota_validation_only_accepts_hard_off_healthy_zero(self):
        row=dict(adaptive=dict(ADAPT='1',HARD_OFF='1',DELAY_PAIRS='1',
            JUMP='20,40',NOISE_Q8='256,1024',LEARNED='100,100'),
            robust_zero=dict(BLOCK='5',SEGMENT='500',SEGMENTS='8',
                OUTLIERS='80',MAX='OFF',SEG_MAX='OFF',SEG_OUTLIERS='0',
                FLAGS='0',HARD_OFF='1'))
        validate_adaptive(row,'OFF','OFF')
        for key,value in [('MAX','20'),('FLAGS','4'),('HARD_OFF','0'),
                          ('SEGMENTS','7'),('SEG_OUTLIERS','1'),('OUTLIERS','801')]:
            bad=copy.deepcopy(row); bad['robust_zero'][key]=value
            with self.assertRaises(RuntimeError): validate_adaptive(bad,'OFF','OFF')


if __name__=='__main__': unittest.main()
