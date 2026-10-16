import unittest
import json
from unittest.mock import patch
from pathlib import Path
import protected_irq_priority_fix_stage as stage
import protected_irq_priority_fix_acceptance as acceptance

class PriorityFixTests(unittest.TestCase):
    def test_exact_image_and_rollback_receipt(self):
        self.assertEqual(len(stage.pinned_image()),206560)
        with self.assertRaises(RuntimeError): stage.verified_baseline(b'',Path('wrong.json'))
    def test_encoder_checks_fail_closed(self):
        good={'encoder_dma':dict(FAIL='0',TIMEOUT='0',IO='0',SCHED='0',STALE='0',READS='500'),
              'encoder_snapshot':dict(VALID='0'), 'encoder_irq':dict(VALID='0',MAX_LATE_US='5')}
        acceptance.validate_encoder(good)
        for group,key,value in (('encoder_dma','TIMEOUT','1'),('encoder_irq','MAX_LATE_US','200'),
                                ('encoder_snapshot','VALID','1')):
            bad={k:v.copy() for k,v in good.items()}; bad[group][key]=value
            with self.subTest(key=key),self.assertRaises(RuntimeError): acceptance.validate_encoder(bad)
        with self.assertRaises(RuntimeError): acceptance.validate_encoder({})
    def test_no_motion_stage_console(self):
        class Port:
            def write(self,_): raise AssertionError('Must not write')
        uart=stage.trace.StageConsole(Port())
        for cmd in ('START','MOTOR TEST SPEED','FW END','FW CONFIRM'):
            with self.subTest(cmd=cmd),self.assertRaises(ValueError): uart.query(cmd)
    def test_baseline_generation_and_bytes_are_bound(self):
        failed=dict(pass_=False,image_sha256=stage.trace.SHA,host_trial_commits=1,
                    host_motor_commands=0,failure='Startup fault; no reset/activation retry',
                    startup_encoder_dma=dict(TIMEOUT='1'),startup_encoder_snapshot=dict(PH='4'),
                    final_outputs_off=True)
        raw=bytes(0x80000)
        with patch.object(Path,'read_text',return_value=json.dumps(failed)), \
             patch.object(stage.trace.old.previous,'private_capture',return_value=raw), \
             patch.object(stage,'latest_meta',return_value=(0,0,1,0,0,490,0,0,0,0)) as meta:
            self.assertEqual(stage.verified_baseline(raw,stage.FAILURE),490)
            with self.assertRaises(RuntimeError): stage.verified_baseline(b'1'+raw[1:],stage.FAILURE)
            meta.return_value=(0,0,1,0,0,486,0,0,0,0)
            with self.assertRaises(RuntimeError): stage.verified_baseline(raw,stage.FAILURE)

if __name__=='__main__': unittest.main()
