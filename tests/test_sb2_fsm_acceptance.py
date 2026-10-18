"""No-device regression for SB2 full-state-machine orchestration."""
import contextlib
import io
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
import sb2_fsm_acceptance as runner
from test_loaded_fsm_motion import FakeBoard,RECIPE


class Sb2Board(FakeBoard):
    def command(self,command,*args):
        line=super().command(command,*args)
        return line+' SPEED_CTRL=SB2' if command=='MOTOR TEST PROFILE' else line


class Sb2FsmTests(unittest.TestCase):
    def run_fake(self,board):
        clock=iter(i*.01 for i in range(20000)); row=dict(postflight={},samples=[])
        with patch.object(runner.fsm,'require_idle_ready'), \
                patch.object(runner.fsm.time,'monotonic',side_effect=lambda:next(clock)), \
                patch.object(runner.fsm,'stop',side_effect=lambda b:b.command('STOP')), \
                contextlib.redirect_stdout(io.StringIO()):
            runner.fsm.execute(board,row,'A',expected_speed_ctrl='SB2')
        return row

    def test_complete_once_through_torque_hold_stop_not_just_speed(self):
        board=Sb2Board([1,2,3,4,5,6,7,9]); row=self.run_fake(board)
        self.assertTrue(row['cycle_pass'])
        self.assertEqual(board.commands.count('START'),1)
        self.assertEqual(row['stages'],[1,2,3,4,5,6,7,9])
        self.assertEqual(board.recipe,RECIPE)
        self.assertIn('ANALOG SAFE',board.commands); self.assertNotIn('SAVE',board.commands)

    def test_fault_stops_and_does_not_restart(self):
        board=Sb2Board([1,2,3],fault=True)
        with self.assertRaisesRegex(RuntimeError,'Fault during cycle'): self.run_fake(board)
        self.assertEqual(board.commands.count('START'),1)
        self.assertIn('STOP',board.commands); self.assertIn('ANALOG SAFE',board.commands)

    def test_missing_stages_cannot_pass(self):
        with self.assertRaisesRegex(RuntimeError,'stages not observed'):
            self.run_fake(Sb2Board([1,2,9]))

    def test_no_contact_times_out_without_recipe_widening(self):
        board=Sb2Board([1]*2000)
        with self.assertRaisesRegex(TimeoutError,'Host cycle deadline'): self.run_fake(board)
        self.assertEqual(board.commands.count('START'),1); self.assertEqual(board.recipe,RECIPE)
        self.assertIn('ANALOG SAFE',board.commands)

    def test_default_and_invalid_physical_flags_never_access_devices(self):
        with patch.object(sys,'argv',['fsm']),patch.object(runner,'debug') as debug, \
                patch.object(runner.sb2.prior,'open_port') as port:
            self.assertEqual(runner.main(),0)
            debug.assert_not_called(); port.assert_not_called()
        for args in (['--inspect-off'],['--execute-powered','x'],['--restore-b-drive-off','x']):
            with patch.object(sys,'argv',['fsm',*args]),patch.object(runner.sb2,'image') as image, \
                    contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit): runner.main()
                image.assert_not_called()

    def test_start_journal_failure_prevents_transmission_and_repeated_start(self):
        board=object.__new__(runner.JournalBoard); board.record={}
        with patch.object(runner.sb2.prior,'checkpoint',side_effect=OSError('journal failed')), \
                patch.object(runner.fsm.RecordedBoard,'send') as send:
            with self.assertRaises(OSError): board.send('START')
            send.assert_not_called()
        with patch.object(runner.fsm.RecordedBoard,'send') as send:
            with self.assertRaisesRegex(RuntimeError,'Second START'): board.send('START')
            send.assert_not_called()

    def test_exact_current_capture_and_preserved_fallback(self):
        data=runner.sb2.image(); raw=runner.baseline(data)
        self.assertEqual(runner.sb2.zero.latest_meta(raw)[2:6],(2,0,0,653))
        self.assertEqual(raw[0x8000:0x8000+len(data)],data)


if __name__=='__main__': unittest.main()
