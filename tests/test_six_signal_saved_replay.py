import copy
import json
from pathlib import Path
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
import six_signal_feedback_replay as replay

CAPTURE=ROOT/'safety_backups/six-signal-live-20261013/capture-1791893656680178300.json'


class SavedReplayTests(unittest.TestCase):
    def test_exact_saved_batches_use_guardian_and_never_qualify_motor(self):
        result=replay.report(CAPTURE)
        self.assertTrue(result['all_numerical_feedback_pass'])
        self.assertFalse(result['bridge_admitted'])
        self.assertFalse(result['motor_qualified'])
        self.assertFalse(result['actual_bridge_switched'])
        for key,repairs in (('off',37),('pwm',39)):
            row=result['batches'][key]
            self.assertEqual(row['input_pairs'],3600)
            self.assertEqual(row['consumed'],3597)
            self.assertEqual(row['repaired'],repairs)
            self.assertEqual(row['trip_seq'],0)
            self.assertEqual(row['timestamps'],'SYNTHETIC_50_US')

    def test_failed_incomplete_unrelated_or_changed_batch_refused(self):
        good=json.loads(CAPTURE.read_text('utf-8'))
        for key,value in (('pass_',False),('final_safe_locked',False),
                          ('bridge_enabled',True),('generation','457'),('image_sha256','wrong')):
            changed=copy.deepcopy(good); changed[key]=value
            with self.subTest(key=key),self.assertRaises(ValueError): replay.validate_capture(changed)
        changed=copy.deepcopy(good); changed['pwm']['samples'].pop()
        with self.assertRaises(RuntimeError): replay.validate_capture(changed)
        changed=copy.deepcopy(good); changed['off']['samples'][0][0]+=1
        with self.assertRaises(RuntimeError): replay.validate_capture(changed)


if __name__=='__main__': unittest.main()
