"""Board-runner gates tested offline; no serial/debugger access."""
import json
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
import deadline_attribution_board_test as board


class DeadlineBoardTests(unittest.TestCase):
    def test_exact_image_and_receipt_pins(self):
        self.assertEqual(len(board.image()),229348)
        with patch.object(board,'SHA','0'*64),self.assertRaises(ValueError): board.image()

    def test_offline_verification_and_page_bounds(self):
        code=('import deadline_attribution_board_test as b,json; from unittest.mock import patch; '
              'b.configure(); '
              'mock=patch.object(b.base.tx,"baseline",return_value=(None,b"")); '
              'mock.start(); b.verify(); mock.stop(); '
              'print(json.dumps(b.base.tx.stage_commands(b.PRIVATE/"live.bin",'
              'b.PRIVATE/"expected.bin",b.PRIVATE/"staged.bin")))')
        p=subprocess.run([sys.executable,'-c',code],cwd=board.ROOT/'tools',
                         capture_output=True,text=True,timeout=30)
        self.assertEqual(p.returncode,0,p.stderr)
        commands=json.loads(p.stdout)
        self.assertTrue(any('AttributionReview/OneCyclePwmPipeline/foc2.bin' in c
                            and '0x08008000 bin' in c for c in commands))
        self.assertTrue(any('verify_image' in c for c in commands))
        self.assertFalse(any(c in ('resume','reset run') or '0x2001FFC0' in c for c in commands))

    def test_physical_power_gate_precedes_device_access(self):
        for mode in ('--stage-inactive-a','--trial-from-stage','--restore-from-trial'):
            args=[mode]+([] if mode=='--stage-inactive-a' else ['unused.json'])
            p=subprocess.run([sys.executable,str(board.ROOT/'tools/deadline_attribution_board_test.py'),*args],
                             capture_output=True,text=True,timeout=30)
            self.assertNotEqual(p.returncode,0)
            self.assertIn('disconnected motor required',p.stderr)

    def test_miss_requires_new_trustworthy_snapshot(self):
        def case(miss,status):
            return dict(timing=dict(deadline_miss=miss),deadline_snapshot=dict(status=status))
        self.assertIsNone(board.attribution_failure(case(1,'VALID_FIRST_MISS')))
        self.assertIsNone(board.attribution_failure(case(0,'NO_SNAPSHOT')))
        for miss,status in ((1,'NO_SNAPSHOT'),(1,'CAPTURED_BUT_UNTRUSTED'),(0,'VALID_FIRST_MISS')):
            self.assertIsNotNone(board.attribution_failure(case(miss,status)))


if __name__=='__main__': unittest.main()
