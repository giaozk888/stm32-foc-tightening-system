"""No hardware: pin checks, phase interlocks, single command and fail-closed runner."""
import contextlib
import io
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock,patch
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
import torque_chain_acceptance as runner


class TorqueAcceptanceTests(unittest.TestCase):
    def test_exact_image_and_preserved_baseline(self):
        self.assertEqual(len(runner.image()),229132)
        self.assertEqual(runner.old.zero.latest_meta(runner.baseline())[2:6],(2,0,0,669))
        with patch.object(runner,'IMAGE',runner.prior.IMAGE):
            with self.assertRaises(ValueError): runner.image()

    def test_default_is_files_only_and_live_modes_require_fresh_power_state(self):
        with patch.object(sys,'argv',['torque']),patch.object(runner,'debug') as debug, \
                patch.object(runner.old.prior,'open_port') as port,contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(runner.main(),0); debug.assert_not_called(); port.assert_not_called()
        for args in (['--stage-off'],['--execute-positive','x'],['--restore-b-drive-off','x']):
            with patch.object(sys,'argv',['torque',*args]),patch.object(runner,'image') as image, \
                    contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit): runner.main()
                image.assert_not_called()

    def test_preflight_failure_never_pulses_and_always_captures_matching_elf(self):
        port=Mock(); port.is_open=True; uart=Mock(); row={}; before=runner.baseline()
        with patch.object(runner,'stage_receipt',return_value=(runner.BASE,before)), \
             patch.object(runner.old.prior,'open_port',return_value=port), \
             patch.object(runner,'TorqueConsole',return_value=uart), \
             patch.object(runner.old.prior,'checkpoint'),patch.object(runner,'debug'), \
             patch.object(runner.old.prior,'wait_health_confirmation'), \
             patch.object(runner,'preflight',side_effect=RuntimeError('preflight')), \
             patch.object(runner.old,'capture_stopped') as capture:
            with self.assertRaisesRegex(RuntimeError,'preflight'):
                runner.execute(row,'mock',runner.BASE,runner.image())
            uart.torque.assert_not_called()
            uart.query.assert_any_call('STOP',.6); uart.query.assert_any_call('ANALOG SAFE',.6)
            capture.assert_called_once_with(row,'mock',before,elf=runner.ELF)

    def console(self):
        c=object.__new__(runner.TorqueConsole); c.request=100
        c.port=Mock(); c.row=dict(commands=[]); c.dispatch=Mock()
        c.read_line=Mock(return_value='101 OK TORQUE QUEUED MANUAL_ONE_SHOT=1')
        return c

    def test_positive_exactly_once_no_negative_offset_or_general_start(self):
        c=self.console()
        with patch.object(runner.old.prior,'checkpoint'):
            self.assertIn('QUEUED',c.torque(runner.COMMAND))
            with self.assertRaises(RuntimeError): c.torque(runner.COMMAND)
            for command in ('START','MOTOR TEST TORQUE NEG ZERO CONFIRM',
                            'MOTOR TEST TORQUE POS PLUS5 CONFIRM'):
                with self.assertRaises(ValueError): c.torque(command)
        c.port.write.assert_called_once_with(b'101 MOTOR TEST TORQUE POS ZERO CONFIRM\r\n')
        self.assertEqual(c.row['pulse_attempts'],1)

    def test_uncertain_ack_cannot_retry(self):
        c=self.console(); c.read_line.return_value=None
        with patch.object(runner.old.prior,'checkpoint'):
            with self.assertRaises(TimeoutError): c.torque(runner.COMMAND,.001)
            with self.assertRaises(RuntimeError): c.torque(runner.COMMAND)
        self.assertEqual(c.port.write.call_count,1)

    def test_stage_cannot_change_B_private_or_metadata(self):
        before=runner.baseline(); data=runner.image(); end=(0x8000+len(data)+0x7ff)&~0x7ff
        raw=bytearray(before); raw[0x8000:end]=data+b'\xff'*(end-0x8000-len(data))
        runner.old.zero.validate_staged(raw,before,data)
        for addr in (0,0x40000,0x7e800,0x7f800):
            bad=raw.copy(); bad[addr]^=1
            with self.assertRaises(ValueError): runner.old.zero.validate_staged(bad,before,data)


if __name__=='__main__': unittest.main()
