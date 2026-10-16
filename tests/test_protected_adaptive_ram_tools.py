"""Offline deployment identity/rollback tests; no serial or SWD calls."""
import copy
import json
from pathlib import Path
import unittest
from unittest.mock import patch
import protected_adaptive_ram_stage as profile
from protected_adaptive_ram_acceptance import validate_ram

class RamDeploymentTests(unittest.TestCase):
    def test_exact_image_and_separate_30_second_observation(self):
        self.assertEqual(len(profile.pinned_image()),206412)
        self.assertEqual(profile.OBSERVE_SECONDS,30.0)
        with patch.object(profile,'SHA','0'*64),self.assertRaises(RuntimeError):
            profile.pinned_image()

    def test_only_proved_a526_and_identical_private_flash_accepted(self):
        receipt=dict(pass_=True,image_sha256=profile.previous.SHA,resets=0,
            motor_commands=0,fallback_healthy=True,all_app_and_private_bytes_unchanged=True,
            failed_b_not_bootable_without_new_staging=True,fw={'GEN':'526'})
        with patch.object(Path,'read_text',return_value=json.dumps(receipt)),\
             patch.object(profile,'latest_meta',return_value=(0,0,1,0,0,526,0,0,0,0)),\
             patch.object(profile.board_profile.previous,'private_capture',return_value=b'exact'):
            self.assertEqual(profile.verified_baseline(b'exact',profile.ORIGINAL),526)
            with self.assertRaises(RuntimeError): profile.verified_baseline(b'changed',profile.ORIGINAL)
            for key,value in [('motor_commands',1),('resets',1),('fallback_healthy',False),
                              ('all_app_and_private_bytes_unchanged',False),('fw',{'GEN':'522'})]:
                bad=copy.deepcopy(receipt); bad[key]=value
                with patch.object(Path,'read_text',return_value=json.dumps(bad)),self.assertRaises(RuntimeError):
                    profile.verified_baseline(b'exact',profile.ORIGINAL)
        with self.assertRaises(RuntimeError):
            profile.verified_baseline(b'exact',profile.OUTPUT/'unrelated.json')

    def test_ram_identity_never_relaxes_deadline_or_hard_off(self):
        row={'ram':dict(ENABLED='1',HARD_OFF='1',DEADLINE_US='50')}
        validate_ram(row)
        for key,value in [('ENABLED','0'),('HARD_OFF','0'),('DEADLINE_US','51')]:
            bad=copy.deepcopy(row); bad['ram'][key]=value
            with self.assertRaises(RuntimeError): validate_ram(bad)

if __name__=='__main__': unittest.main()
