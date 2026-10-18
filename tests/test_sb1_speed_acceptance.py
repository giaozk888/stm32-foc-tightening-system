"""No-board tests for the single START/2s speed acceptance and cleanup."""
import contextlib
import io
from pathlib import Path
import sys
import json
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
import sb1_speed_acceptance as runner
from test_loaded_fsm_motion import FakeBoard,RECIPE


class FakeSpeedBoard(FakeBoard):
    def __init__(self,fault=False,marker='SB1'):
        super().__init__([1]*100,fault)
        self.marker=marker

    def command(self,command,*args):
        if command=='MOTOR TEST PROFILE':
            return super().command(command,*args)+' SPEED_CTRL='+self.marker
        if command=='MOTOR TEST STATUS':
            return super().command(command,*args)+' FLAGS=0'
        if command=='STATUS':
            self.commands.append(command)
            return 'OK STATUS MODE=IDLE BUSY=0 FLT=0 CTRL=0.0rpm'
        return super().command(command,*args)

    def send(self,command):
        request=super().send(command)
        if command=='STATUS': self.queued[-1]+=' MODE=SPD CTRL=20.0rpm'
        return request


class SpeedAcceptanceTests(unittest.TestCase):
    def timing_fake(self,*,publish_at=5.0,fault=False,values=None):
        clock=[0.0]
        class Uart:
            lines=[]
            def poll(self,delay):
                clock[0]+=delay
                if clock[0]>=publish_at:
                    self.lines=(values or ['FOC TIMING wall_max_us=27.15','FOC TIMING deadline_miss=0',
                        'PWM COMMIT actual_late_commit_count=0','PWM COMMIT actual_margin_min_us=16.63'])
            def query(self,*args):
                return 'OK STATE=%s USED=0 FAULT=0 FLAGS=0 SD=0 MOE=0 CCER=0'%('4' if fault else '1')
        with patch.object(runner.time,'monotonic',side_effect=lambda:clock[0]):
            result=runner.wait_timing(Uart(),{})
        return result,clock[0]

    def test_waits_for_real_five_second_monitor(self):
        result,elapsed=self.timing_fake()
        self.assertGreaterEqual(elapsed,5)
        self.assertLess(elapsed,8)
        self.assertEqual(result['wall_max_us'],27.15)

    def test_missing_partial_or_fault_timing_never_passes(self):
        with self.assertRaises(TimeoutError): self.timing_fake(publish_at=20)
        with self.assertRaises(TimeoutError): self.timing_fake(values=['FOC TIMING wall_max_us=27'])
        with self.assertRaises(RuntimeError): self.timing_fake(fault=True)
        with self.assertRaises(RuntimeError): self.timing_fake(values=[
            'FOC TIMING wall_max_us=51','deadline_miss=1',
            'actual_late_commit_count=0 actual_margin_min_us=16'])

    def test_checkpoint_is_durable_before_start_and_retains_old_on_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'receipt.json'
            row=dict(receipt_path=str(path),start_attempts=0,pass_=False)
            runner.checkpoint(row,'prepared_no_start')
            self.assertEqual(json.loads(path.read_text())['start_attempts'],0)
            row['start_attempts']=1; runner.checkpoint(row,'START_ATTEMPT')
            saved=json.loads(path.read_text())
            self.assertEqual(saved['phase'],'START_ATTEMPT')
            with patch.object(runner.os,'replace',side_effect=OSError('blocked')):
                with self.assertRaises(OSError): runner.checkpoint(row,'START_ACK')
            self.assertEqual(json.loads(path.read_text()),saved)

    def test_persist_failure_before_start_never_sends_start(self):
        board=FakeSpeedBoard(); record=dict(samples=[],postflight={})
        original=runner.checkpoint
        def fail_start(row,phase):
            if phase=='START_ATTEMPT': raise OSError('journal failed')
            return original(row,phase)
        with patch.object(runner,'checkpoint',side_effect=fail_start):
            with self.assertRaisesRegex(OSError,'journal failed'): self.run_fake(board,record)
        self.assertNotIn('START',board.commands)
        self.assertIn('ANALOG SAFE',board.commands)

    def run_fake(self,board,record):
        clock=iter(i*.001 for i in range(20000))
        with patch.object(runner,'require_idle_ready'),\
                patch.object(runner.time,'monotonic',side_effect=lambda:next(clock)),\
                contextlib.redirect_stdout(io.StringIO()):
            runner.motion(board,record)

    def test_one_start_two_seconds_stop_and_restore(self):
        board=FakeSpeedBoard(); record=dict(samples=[],postflight={})
        self.run_fake(board,record)
        self.assertEqual(board.commands.count('START'),1)
        self.assertTrue(record['motion_pass']); self.assertTrue(record['recipe_restored'])
        self.assertTrue(record['stop_feedback_pass'])
        self.assertLess(record['host_stop_elapsed_s'],2.1)
        self.assertEqual(board.recipe,RECIPE)
        self.assertLess(board.commands.index('ANALOG SAFE'),board.commands.index('SET RUNDOWN_RPM 70'))
        self.assertEqual(record['speed_summary']['tail_mean_filtered_rpm'],20)

    def test_fault_never_restarts_and_still_latches(self):
        board=FakeSpeedBoard(fault=True); record=dict(samples=[],postflight={})
        with self.assertRaisesRegex(RuntimeError,'Protection fault'):
            self.run_fake(board,record)
        self.assertEqual(board.commands.count('START'),1)
        self.assertIn('STOP',board.commands); self.assertIn('ANALOG SAFE',board.commands)
        self.assertEqual(board.recipe,RECIPE)

    def test_wrong_controller_never_starts(self):
        board=FakeSpeedBoard(marker='OLD'); record=dict(samples=[],postflight={})
        with self.assertRaises(RuntimeError): self.run_fake(board,record)
        self.assertNotIn('START',board.commands)
        self.assertIn('ANALOG SAFE',board.commands)

    def test_existing_short_recipe_is_not_widened(self):
        board=FakeSpeedBoard(); board.recipe['RUNDOWN_TIMEOUT_MS']=1000
        with self.assertRaises(RuntimeError): self.run_fake(board,dict(samples=[],postflight={}))
        self.assertNotIn('START',board.commands)
        self.assertEqual(board.recipe['RUNDOWN_TIMEOUT_MS'],1000)

    def test_summary_cannot_accept_missing_nonfinite_or_bad_tracking(self):
        rows=[dict(elapsed_s=i*.05,status=dict(CTRL='20rpm')) for i in range(1,40)]
        self.assertTrue(runner.speed_summary(rows)['tracking_pass'])
        with self.assertRaises(ValueError): runner.speed_summary(rows[:10])
        rows[-1]['status']['CTRL']='nanrpm'
        with self.assertRaises(ValueError): runner.speed_summary(rows)
        rows[-1]['status']['CTRL']='30rpm'
        self.assertFalse(runner.speed_summary(rows)['tracking_pass'])

    def test_default_does_not_inspect_or_open_port(self):
        with patch.object(sys,'argv',['speed']),patch.object(runner,'inspect') as inspect,\
                patch.object(runner,'open_port') as port:
            self.assertEqual(runner.main(),0)
            inspect.assert_not_called(); port.assert_not_called()

    def test_physical_gates_precede_files_or_device_access(self):
        for args in (['--inspect-off'],['--execute-powered','x']):
            with patch.object(sys,'argv',['speed',*args]),patch.object(runner,'baseline') as base,\
                    contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit): runner.main()
                base.assert_not_called()


if __name__=='__main__': unittest.main()
