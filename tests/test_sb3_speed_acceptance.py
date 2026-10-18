"""Device-free checks on SB3 binding, single START, stop and failure cleanup."""
import contextlib
import io
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock,patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
import sb3_speed_acceptance as runner
from test_sb1_speed_acceptance import FakeSpeedBoard
from test_loaded_fsm_motion import FakeBoard,RECIPE


class FullBoard(FakeBoard):
    def command(self,command,*args):
        line=super().command(command,*args)
        return line+' SPEED_CTRL=SB3' if command=='MOTOR TEST PROFILE' else line


class Sb3AcceptanceTests(unittest.TestCase):
    def run_motion(self,board,row):
        clock=iter(i*.001 for i in range(20000))
        with patch.object(runner.old.prior,'require_idle_ready'), \
                patch.object(runner.old.prior.time,'monotonic',side_effect=lambda:next(clock)), \
                contextlib.redirect_stdout(io.StringIO()):
            runner.old.prior.motion(board,row,expected_speed_ctrl='SB3')

    def test_exact_image_elf_and_preserved_B661(self):
        self.assertEqual(len(runner.image()),229036)
        self.assertEqual(runner.old.zero.latest_meta(runner.baseline())[2:6],(2,0,0,661))

    def test_old_sb2_is_not_new_candidate(self):
        with patch.object(runner,'IMAGE',runner.voltage.IMAGE):
            with self.assertRaises(ValueError): runner.image()

    def test_default_no_hardware_and_physical_gates_precede_access(self):
        with patch.object(sys,'argv',['sb3']),patch.object(runner,'debug') as debug, \
                patch.object(runner.old.prior,'open_port') as port:
            self.assertEqual(runner.main(),0); debug.assert_not_called(); port.assert_not_called()
        for args in (['--stage-off'],['--execute-powered','x'],['--restore-b-drive-off','x']):
            with patch.object(sys,'argv',['sb3',*args]),patch.object(runner,'image') as image, \
                    contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit): runner.main()
                image.assert_not_called()

    def test_one_start_two_seconds_stop_and_recipe_restore(self):
        board=FakeSpeedBoard(marker='SB3'); row=dict(samples=[],postflight={})
        self.run_motion(board,row)
        self.assertEqual(board.commands.count('START'),1)
        self.assertTrue(row['motion_pass']); self.assertTrue(row['recipe_restored'])
        self.assertLess(row['host_stop_elapsed_s'],2.1)
        self.assertIn('ANALOG SAFE',board.commands); self.assertNotIn('SAVE',board.commands)

    def test_fault_stops_without_retry_and_wrong_marker_never_starts(self):
        board=FakeSpeedBoard(marker='SB3',fault=True)
        with self.assertRaisesRegex(RuntimeError,'Protection fault'):
            self.run_motion(board,dict(samples=[],postflight={}))
        self.assertEqual(board.commands.count('START'),1)
        self.assertIn('STOP',board.commands); self.assertIn('ANALOG SAFE',board.commands)
        board=FakeSpeedBoard(marker='SB2')
        with self.assertRaises(RuntimeError): self.run_motion(board,dict(samples=[],postflight={}))
        self.assertNotIn('START',board.commands)

    def test_failed_preflight_captures_new_elf_and_never_starts(self):
        port=Mock(); port.is_open=True; uart=Mock(); uart.lines=[]; before=runner.baseline(); row={}
        with patch.object(runner,'stage_receipt',return_value=(runner.BASE,before)), \
                patch.object(runner.old.prior,'open_port',return_value=port), \
                patch.object(runner.old.prior,'JournalConsole',return_value=uart), \
                patch.object(runner.old.prior,'checkpoint'),patch.object(runner,'debug'), \
                patch.object(runner.old.prior,'wait_health_confirmation',side_effect=RuntimeError('preflight failed')), \
                patch.object(runner.old.prior,'motion') as motion, \
                patch.object(runner.old,'capture_stopped') as capture:
            with self.assertRaisesRegex(RuntimeError,'preflight failed'):
                runner.execute(row,'mock',runner.BASE,runner.image())
            motion.assert_not_called(); capture.assert_called_once_with(row,'mock',before,elf=runner.ELF)

    def test_staging_never_changes_other_regions(self):
        data=runner.image(); before=runner.baseline(); end=(0x8000+len(data)+0x7ff)&~0x7ff
        staged=bytearray(before); staged[0x8000:end]=data+b'\xff'*(end-0x8000-len(data))
        runner.old.zero.validate_staged(staged,before,data)
        for offset in (0,0x40000,0x7e800,0x7f800):
            bad=staged.copy(); bad[offset]^=1
            with self.assertRaises(ValueError): runner.old.zero.validate_staged(bad,before,data)

    def run_full(self,board,row):
        clock=iter(i*.01 for i in range(20000))
        with patch.object(runner.voltage.cycle.fsm,'require_idle_ready'), \
                patch.object(runner.voltage.cycle.fsm.time,'monotonic',side_effect=lambda:next(clock)), \
                patch.object(runner.voltage.cycle.fsm,'stop',side_effect=lambda b:b.command('STOP')), \
                contextlib.redirect_stdout(io.StringIO()):
            runner.motion(board,row,full_fsm=True)

    def test_full_fsm_does_not_stop_at_contact_and_restores_recipe(self):
        board=FullBoard([1,2,3,4,5,6,7,9]); row=dict(samples=[],postflight={})
        self.run_full(board,row)
        self.assertTrue(row['cycle_pass']); self.assertEqual(row['stages'],[1,2,3,4,5,6,7,9])
        self.assertEqual(board.commands.count('START'),1); self.assertEqual(board.recipe,RECIPE)
        self.assertIn('ANALOG SAFE',board.commands); self.assertNotIn('SAVE',board.commands)

    def test_full_fsm_fault_and_missing_stage_do_not_pass_or_retry(self):
        board=FullBoard([1],fault=True)
        with self.assertRaisesRegex(RuntimeError,'Fault during cycle'):
            self.run_full(board,dict(samples=[],postflight={}))
        self.assertEqual(board.commands.count('START'),1); self.assertIn('ANALOG SAFE',board.commands)
        with self.assertRaisesRegex(RuntimeError,'stages not observed'):
            self.run_full(FullBoard([1,2,9]),dict(samples=[],postflight={}))

    def test_full_mode_cannot_skip_powered_authorization(self):
        for args in (['--full-state-machine'],['--execute-powered','x','--full-state-machine']):
            with patch.object(sys,'argv',['sb3',*args]),patch.object(runner,'image') as image, \
                    contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit): runner.main()
                image.assert_not_called()


if __name__=='__main__': unittest.main()
