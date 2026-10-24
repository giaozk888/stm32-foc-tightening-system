"""Files and transport mocks only; no hardware access."""
import json
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
import current_step_gate_board as gate
import current_step_ab_board as step
from test_current_step_ab_board import FakeBoard
import test_current_step_ab_board as legacy_tests

class GateBoardTests(unittest.TestCase):
    def tearDown(self):
        for k,value in gate.LEGACY.items():setattr(step,k,value)
        gate.LEGACY['configure']()

    def test_exact_new_image_and_original_stopped_b896_identity(self):
        with patch.object(step.base.hw,'debug') as debug,patch.object(step.base.support.support,'open_port') as serial:
            self.assertEqual(len(gate.image()),213964)
            gate.configure()
            self.assertEqual(step.base.EXPECT_META[2:6],(2,0,0,896))
            self.assertEqual(step.base.BASE_RESTORE_RECEIPT,gate.RESTORE.resolve())
            self.assertEqual(step.base.SHA,gate.SHA)
            self.assertEqual(step.ELF,gate.ELF)
            step.base.baseline()
            debug.assert_not_called();serial.assert_not_called()

    def test_default_only_files_and_import_does_not_select_new(self):
        self.assertEqual(step.SHA,gate.LEGACY['SHA'])
        p=subprocess.run([sys.executable,str(ROOT/'tools/current_step_gate_board.py')],
                         capture_output=True,text=True,timeout=15)
        self.assertEqual(p.returncode,0,p.stdout+p.stderr)
        self.assertIn('B896 baseline; no devices',p.stdout)

    def test_new_image_restore_b900_also_requires_full_identity(self):
        receipt=ROOT/'tmp/current-step-ab-restore-1792573553886125200.json'
        with patch.object(step.base.hw,'debug') as debug,patch.object(step.base.support.support,'open_port') as serial:
            gate.configure(receipt)
            self.assertEqual(step.base.EXPECT_META[2:6],(2,0,0,900))
            self.assertEqual(step.base.BASE_RESTORE_RECEIPT,receipt.resolve())
            self.assertEqual(step.base.baseline()[0x8000:0x8000+len(gate.image())],gate.image())
            debug.assert_not_called();serial.assert_not_called()

    def test_bad_restore_and_missing_physical_flags_never_access_device(self):
        with patch.object(step.base.hw,'debug') as debug,patch.object(step.base.support.support,'open_port') as serial:
            with self.assertRaises(ValueError):
                gate.configure(ROOT/'tmp/current-step-ab-run-1792572252465902700.json')
            for args in (['--stage-off'],['--execute-powered','unused'],['--restore-b-drive-off','unused']):
                with self.assertRaises(SystemExit):gate.main(args)
            debug.assert_not_called();serial.assert_not_called()

    def test_same_one_command_and_stop_on_unknown_ack(self):
        for refuse in (False,True):
            board=FakeBoard(refuse);row=dict(postflight={})
            with legacy_tests.StepBoardTests().fixture():
                if refuse:
                    with self.assertRaises(TimeoutError):step.motion(board,row)
                else:step.motion(board,row)
            self.assertEqual(board.calls.count(step.COMMAND),1)
            self.assertNotIn('START',board.calls)
            self.assertIn('MOTOR TEST STOP',board.calls)
            self.assertIn('ANALOG SAFE',board.calls)

if __name__=='__main__':unittest.main()
