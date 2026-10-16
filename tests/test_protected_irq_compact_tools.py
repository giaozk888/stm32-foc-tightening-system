"""Offline identity, baseline and unchanged-deadline gates. No board I/O."""
import copy
import json
from pathlib import Path
import unittest
from unittest.mock import patch
import protected_irq_compact_stage as profile
from protected_irq_compact_acceptance import validate_compact

class CompactToolTests(unittest.TestCase):
    def test_exact_binary_and_30_second_observation(self):
        self.assertEqual(len(profile.pinned_image()),207196)
        self.assertEqual(profile.OBSERVE_SECONDS,30.0)
        with patch.object(profile,'SHA','0'*64),self.assertRaises(RuntimeError):
            profile.pinned_image()

    def test_only_proved_a530_with_identical_flash(self):
        receipt=dict(pass_=True,image_sha256=profile.previous.SHA,resets=0,
            motor_commands=0,fallback_healthy=True,all_app_and_private_bytes_unchanged=True,
            failed_b_not_bootable_without_new_staging=True,fw={'GEN':'530'})
        with patch.object(Path,'read_text',return_value=json.dumps(receipt)),\
             patch.object(profile,'latest_meta',return_value=(0,0,1,0,0,530,0,0,0,0)),\
             patch.object(profile.board_profile.previous,'private_capture',return_value=b'exact'):
            self.assertEqual(profile.verified_baseline(b'exact',profile.ORIGINAL),530)
            with self.assertRaises(RuntimeError): profile.verified_baseline(b'changed',profile.ORIGINAL)
            for key,value in [('motor_commands',1),('resets',1),('fallback_healthy',False),
                              ('all_app_and_private_bytes_unchanged',False),('fw',{'GEN':'526'})]:
                bad=copy.deepcopy(receipt); bad[key]=value
                with patch.object(Path,'read_text',return_value=json.dumps(bad)),self.assertRaises(RuntimeError):
                    profile.verified_baseline(b'exact',profile.ORIGINAL)
        with self.assertRaises(RuntimeError):
            profile.verified_baseline(b'exact',profile.OUTPUT/'unrelated.json')

    def test_ram_and_compact_identity_cannot_relax_limits(self):
        row={'ram':dict(ENABLED='1',HARD_OFF='1',DEADLINE_US='50'),
             'compact':dict(ENABLED='1',HARD_OFF='1',FIXED_OPS='1',GUARD_US='25',DEADLINE_US='50')}
        validate_compact(row)
        for field,values in [('ram',[('HARD_OFF','0'),('DEADLINE_US','51')]),
            ('compact',[('ENABLED','0'),('HARD_OFF','0'),('FIXED_OPS','0'),('GUARD_US','50'),('DEADLINE_US','51')])]:
            for key,value in values:
                bad=copy.deepcopy(row); bad[field][key]=value
                with self.assertRaises(RuntimeError): validate_compact(bad)

if __name__=='__main__': unittest.main()
