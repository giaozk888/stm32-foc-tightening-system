"""Offline runner gates/ownership/verdict regression. Never access devices."""
import copy
import json
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
import pwm_pipeline_board_test as board

class PipelineBoardTests(unittest.TestCase):
    def test_image_pins_and_fail_closed_hash(self):
        self.assertEqual(len(board.image()),229236)
        with patch.object(board,'SHA','0'*64):
            with self.assertRaises(ValueError): board.image()

    def test_offline_verification_and_stage_page_bounds(self):
        code=('import pwm_pipeline_board_test as b,json; from unittest.mock import patch; '
              'b.configure(); '
              'mock=patch.object(b.base.tx,"baseline",return_value=(None,b"")); '
              'mock.start(); b.verify(); mock.stop(); '
              'print(json.dumps(b.base.tx.stage_commands(b.PRIVATE/"live.bin",'
              'b.PRIVATE/"expected.bin",b.PRIVATE/"staged.bin")))')
        p=subprocess.run([sys.executable,'-c',code],cwd=board.ROOT/'tools',
                         capture_output=True,text=True,timeout=30)
        self.assertEqual(p.returncode,0,p.stderr)
        commands=json.loads(p.stdout)
        self.assertTrue(any('0x08008000 bin' in c for c in commands))
        self.assertTrue(any('verify_image' in c for c in commands))
        self.assertFalse(any(c in ('resume','reset run') or '0x2001FFC0' in c for c in commands))

    def test_power_gate_before_device_access(self):
        for mode in ('--stage-inactive-a','--trial-from-stage','--restore-from-trial'):
            args=[mode]+([] if mode=='--stage-inactive-a' else ['unused.json'])
            p=subprocess.run([sys.executable,str(board.ROOT/'tools/pwm_pipeline_board_test.py'),*args],
                             capture_output=True,text=True,timeout=30)
            self.assertNotEqual(p.returncode,0)
            self.assertIn('disconnected motor required',p.stderr)

    def test_zero_writes_or_late_cannot_pass(self):
        p=dict(priorities=dict(ok=1,unexpected=0),timing=dict(frames=100,deadline_miss=0),
               pipeline=dict(generated=99,tim7_preempt_max_cycles=0),
               actual_ccr=dict(actual_ccr_writes=99,points=99,actual_late_count=0,
                   latch_crossings=0,late_update_count=0,invalid=0,blocked=0,post_unsafe=0,
                   possible_mixed_latch_count=0,pwm_update_margin_ticks_min=3000))
        self.assertIsNone(board.acceptance_failure(p))
        for section,key,value in (('actual_ccr','actual_ccr_writes',0),
            ('actual_ccr','points',0),('actual_ccr','actual_late_count',1),
            ('actual_ccr','blocked',1),('actual_ccr','invalid',1),
            ('actual_ccr','post_unsafe',1),('actual_ccr','latch_crossings',1),
            ('actual_ccr','pwm_update_margin_ticks_min',170),
            ('timing','deadline_miss',1),('priorities','ok',0),
            ('pipeline','tim7_preempt_max_cycles',1)):
            case=copy.deepcopy(p); case[section][key]=value
            with self.subTest(section=section,key=key):
                self.assertIsNotNone(board.acceptance_failure(case))

if __name__=='__main__': unittest.main()
