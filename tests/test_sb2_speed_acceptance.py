"""SB2 host orchestration regression; never accesses a device."""
import contextlib
import io
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
import sb2_speed_acceptance as runner
from test_sb1_speed_acceptance import FakeSpeedBoard


class Sb2AcceptanceTests(unittest.TestCase):
    def run_motion(self,board,row):
        clock=iter(i*.001 for i in range(20000))
        with patch.object(runner.prior,'require_idle_ready'), \
                patch.object(runner.prior.time,'monotonic',side_effect=lambda:next(clock)), \
                contextlib.redirect_stdout(io.StringIO()):
            runner.prior.motion(board,row,expected_speed_ctrl='SB2')

    def test_exact_bin_elf_baseline(self):
        data=runner.image(); old=runner.baseline()
        self.assertEqual(len(data),228500)
        self.assertIn(b'SPEED_CTRL=SB2',data)
        self.assertEqual(runner.zero.latest_meta(old)[2:6],(2,0,0,649))

    def test_default_no_device_access(self):
        with patch.object(sys,'argv',['sb2']),patch.object(runner,'debug') as debug, \
                patch.object(runner.prior,'open_port') as port:
            self.assertEqual(runner.main(),0)
            debug.assert_not_called(); port.assert_not_called()

    def test_physical_gates_before_files_and_devices(self):
        for args in (['--stage-off'],['--execute-powered','x'],['--restore-b-drive-off','x']):
            with patch.object(sys,'argv',['sb2',*args]),patch.object(runner,'image') as image, \
                    contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit): runner.main()
                image.assert_not_called()

    def test_sb2_one_start_stop_and_temporary_recipe_restore(self):
        board=FakeSpeedBoard(marker='SB2'); row=dict(samples=[],postflight={})
        self.run_motion(board,row)
        self.assertEqual(board.commands.count('START'),1)
        self.assertTrue(row['motion_pass']); self.assertTrue(row['recipe_restored'])
        self.assertTrue(row['stop_feedback_pass'])
        self.assertLess(row['host_stop_elapsed_s'],2.1)
        self.assertIn('ANALOG SAFE',board.commands)
        self.assertNotIn('SAVE',board.commands)

    def test_sb1_marker_rejected_without_start(self):
        board=FakeSpeedBoard(marker='SB1')
        with self.assertRaises(RuntimeError): self.run_motion(board,dict(samples=[],postflight={}))
        self.assertNotIn('START',board.commands)
        self.assertIn('ANALOG SAFE',board.commands)

    def test_fault_stops_never_retries(self):
        board=FakeSpeedBoard(marker='SB2',fault=True)
        with self.assertRaisesRegex(RuntimeError,'Protection fault'):
            self.run_motion(board,dict(samples=[],postflight={}))
        self.assertEqual(board.commands.count('START'),1)
        self.assertIn('STOP',board.commands); self.assertIn('ANALOG SAFE',board.commands)

    def test_staging_region_validation_rejects_outside_changes(self):
        data=runner.image(); before=runner.baseline(); end=(0x8000+len(data)+0x7ff)&~0x7ff
        staged=bytearray(before); staged[0x8000:end]=data+b'\xff'*(end-0x8000-len(data))
        runner.zero.validate_staged(staged,before,data)
        for offset in (0,0x40000,0x7e800,0x7f800):
            bad=staged.copy(); bad[offset]^=1
            with self.assertRaises(ValueError): runner.zero.validate_staged(bad,before,data)


if __name__=='__main__': unittest.main()
