import json
from pathlib import Path
from unittest.mock import patch
import unittest
import protected_fast_math_stage as stage
import protected_fast_math_acceptance as accept

class FastMathAcceptanceTests(unittest.TestCase):
    def test_exact_image_and_no_motion(self):
        self.assertEqual(len(stage.pinned_image()),203176)
        self.assertTrue(stage.REQUIRE_COST)
        with self.assertRaises(RuntimeError): stage.verified_baseline(b'',Path('wrong.json'))
        class Port:
            def write(self,_): raise AssertionError('No writes')
        uart=stage.previous.trace.StageConsole(Port())
        for cmd in ('START','MOTOR TEST SPEED','FW END','FW CONFIRM'):
            with self.assertRaises(ValueError): uart.query(cmd)
    def test_cost_required_and_no_budget_bypass(self):
        good={'cost':dict(TRIG='POLY9_8',DWT='1',CPU_MAX_CYC='4000',
                         PREEMPT_MAX_CYC='2000',PAIR_MAX_US='5',MATH_MAX_US='29')}
        accept.validate_cost(good)
        with self.assertRaises(RuntimeError): accept.validate_cost({})
        for k,v in (('DWT','0'),('CPU_MAX_CYC','0'),('MATH_MAX_US','0'),('PAIR_MAX_US','-1')):
            bad={'cost':good['cost'].copy()}; bad['cost'][k]=v
            with self.subTest(k=k),self.assertRaises(RuntimeError): accept.validate_cost(bad)
    def test_baseline_binds_full_rollback_bytes(self):
        failed=dict(pass_=False,image_sha256=stage.previous.SHA,host_trial_commits=1,
                    host_motor_commands=0,failure='Startup fault; no reset/activation retry',
                    startup_sample={'state':{'FLAGS':'256'},'timing':{'MAX_US':'65'}},
                    final_outputs_off=True)
        rollback=dict(pass_=True,motor_commands=0,resets=0,all_app_and_private_bytes_unchanged=True,
                      failure_receipt=str(stage.FAILURE),fw={'GEN':'494'})
        raw=bytes(0x80000)
        with patch.object(Path,'read_text',side_effect=[json.dumps(failed),json.dumps(rollback)]*3), \
             patch.object(stage.previous.trace.old.previous,'private_capture',return_value=raw), \
             patch.object(stage,'latest_meta',return_value=(0,0,1,0,0,494,0,0,0,0)) as meta:
            self.assertEqual(stage.verified_baseline(raw,stage.FAILURE),494)
            with self.assertRaises(RuntimeError): stage.verified_baseline(b'1'+raw[1:],stage.FAILURE)
            meta.return_value=(0,0,1,0,0,490,0,0,0,0)
            with self.assertRaises(RuntimeError): stage.verified_baseline(raw,stage.FAILURE)

if __name__=='__main__': unittest.main()
