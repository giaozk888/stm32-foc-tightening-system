"""No hardware: same-image negative-only one-shot and sign-bound decoding."""
import contextlib
import io
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock,patch
from test_torque_chain_100ma import capture

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
import torque_chain_100ma_negative as runner


class NegativeTorqueTests(unittest.TestCase):
    def test_same_tested_image_B677_and_default_no_devices(self):
        self.assertEqual(len(runner.image()),229044)
        self.assertEqual(runner.old.zero.latest_meta(runner.baseline())[2:6],(2,0,0,677))
        with patch.object(sys,'argv',['negative']),patch.object(runner,'debug') as debug, \
             patch.object(runner.old.prior,'open_port') as port,contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(runner.main(),0); debug.assert_not_called(); port.assert_not_called()

    def test_each_live_phase_requires_power_assertion(self):
        for args in (['--inspect-off'],['--execute-negative','x'],['--restore-b-drive-off','x']):
            with patch.object(sys,'argv',['negative',*args]),patch.object(runner,'image') as image, \
                 contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit): runner.main()
                image.assert_not_called()

    def console(self):
        c=object.__new__(runner.NegativeConsole); c.request=100; c.port=Mock()
        c.row=dict(commands=[]); c.dispatch=Mock()
        c.read_line=Mock(return_value='101 OK TORQUE QUEUED MANUAL_ONE_SHOT=1')
        return c

    def test_one_negative_only_no_positive_sweep_or_start(self):
        c=self.console()
        with patch.object(runner.old.prior,'checkpoint'):
            c.torque(runner.COMMAND)
            with self.assertRaises(RuntimeError): c.torque(runner.COMMAND)
            for cmd in ('START','MOTOR TEST TORQUE POS ZERO CONFIRM','MOTOR TEST TORQUE NEG PLUS5 CONFIRM'):
                with self.assertRaises(ValueError): c.torque(cmd)
        c.port.write.assert_called_once_with(b'101 MOTOR TEST TORQUE NEG ZERO CONFIRM\r\n')

    def test_missing_ack_never_retries(self):
        c=self.console(); c.read_line.return_value=None
        with patch.object(runner.old.prior,'checkpoint'):
            with self.assertRaises(TimeoutError): c.torque(runner.COMMAND,.001)
            with self.assertRaises(RuntimeError): c.torque(runner.COMMAND)
        self.assertEqual(c.port.write.call_count,1)

    def test_failed_preflight_no_pulse_always_same_ELF_capture(self):
        port=Mock(); port.is_open=True; uart=Mock(); row={}; before=runner.baseline()
        with patch.object(runner,'inspection_receipt',return_value=(runner.BASE,before)), \
             patch.object(runner.old.prior,'open_port',return_value=port), \
             patch.object(runner,'NegativeConsole',return_value=uart), \
             patch.object(runner.old.prior,'checkpoint'),patch.object(runner,'debug'), \
             patch.object(runner.old.prior,'wait_health_confirmation'), \
             patch.object(runner.positive,'preflight',side_effect=RuntimeError('preflight')), \
             patch.object(runner.old,'capture_stopped') as capture_mock:
            with self.assertRaisesRegex(RuntimeError,'preflight'):
                runner.execute(row,'mock',runner.BASE,runner.image())
            uart.torque.assert_not_called()
            uart.query.assert_any_call('STOP',.6); uart.query.assert_any_call('ANALOG SAFE',.6)
            capture_mock.assert_called_once_with(row,'mock',before,elf=runner.ELF)

    def test_readback_does_not_program_reset_or_activate(self):
        row={}; data=runner.image(); raw=runner.baseline()
        with patch.object(runner,'debug',return_value='mock') as debug, \
             patch.object(Path,'read_bytes',return_value=raw), \
             patch.object(runner,'baseline',return_value=raw), \
             patch.object(runner,'check_off',return_value={}):
            runner.inspect(row,'negative-mock',data)
        commands=';'.join(debug.call_args.args[1])
        for denied in ('reset','flash write','resume','mww','mmw'):
            self.assertNotIn(denied,commands)
        self.assertFalse(row['programming_attempted']); self.assertFalse(row['activation'])

    def test_negative_classification_checks_ref_sign_and_metadata(self):
        data=capture([-i*.1 for i in range(12)],-1)
        for i in range(12):
            values=list(runner.positive.decoder.startup.FRAME.unpack_from(data,i*124))
            values[39]=3; values[40]=3
            runner.positive.decoder.startup.FRAME.pack_into(data,i*124,*values)
        meta=dict(iq_mA=100,sign=-1,offset_electrical_deg=0,used=1,queued=0,active=0,admitting=0,denied=0)
        row=dict(pulse_attempts=1,postflight_state=dict(STATE='3'),
            snapshot=dict(first_fault=dict(valid=0),timing=dict(wall_max_us=30,deadline_miss=0,
                actual_late_count=0,actual_margin_min_us=12)),final_cpu_halted=True,
            final_outputs_off=True,all_app_private_unchanged=True)
        with patch.object(runner.positive.decoder,'metadata',return_value=meta), \
             patch.object(runner.positive.decoder.startup,'extract',return_value=data):
            runner.positive.classify(row,b'',expected_sign=-1)
            self.assertTrue(row['pass_']); self.assertEqual(row['torque_diagnostic']['Iq_command_A'],-.1)
            with self.assertRaises(ValueError): runner.positive.classify(row,b'')
            values=list(runner.positive.decoder.startup.FRAME.unpack_from(data,0))
            values[10]=.1; runner.positive.decoder.startup.FRAME.pack_into(data,0,*values)
            runner.positive.classify(row,b'',expected_sign=-1); self.assertFalse(row['pass_'])


if __name__=='__main__': unittest.main()
