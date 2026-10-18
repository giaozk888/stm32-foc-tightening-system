"""No hardware tests for exact voltage-trial binding and fault cleanup."""
import contextlib
import io
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock,patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
import voltage_x2_board_test as runner


class VoltageBoardTests(unittest.TestCase):
    def test_exact_new_identity_and_fallback(self):
        data=runner.image(); before=runner.baseline()
        self.assertEqual(len(data),228532)
        self.assertEqual(runner.sb2.zero.latest_meta(before)[2:6],(2,0,0,657))
        self.assertNotEqual(runner.SHA,runner.sb2.SHA)
        self.assertIn(b'VLIMIT_MV=1600 ILIMIT_MV=750',data)

    def test_old_point_eight_image_cannot_be_mislabelled(self):
        with patch.object(runner,'IMAGE',runner.sb2.IMAGE):
            with self.assertRaises(ValueError): runner.image()

    def test_default_no_hardware_and_physical_gates_before_files(self):
        with patch.object(sys,'argv',['voltage']),patch.object(runner,'debug') as debug, \
                patch.object(runner.sb2.prior,'open_port') as port:
            self.assertEqual(runner.main(),0)
            debug.assert_not_called(); port.assert_not_called()
        for args in (['--stage-off'],['--execute-powered','x'],['--restore-b-drive-off','x']):
            with patch.object(sys,'argv',['voltage',*args]),patch.object(runner,'image') as image, \
                    contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit): runner.main()
                image.assert_not_called()

    def test_stage_compare_rejects_any_outside_slot_change(self):
        before=runner.baseline(); data=runner.image(); end=(0x8000+len(data)+0x7ff)&~0x7ff
        staged=bytearray(before); staged[0x8000:end]=data+b'\xff'*(end-0x8000-len(data))
        runner.sb2.zero.validate_staged(staged,before,data)
        for off in (0,0x40000,0x7e800,0x7f800):
            altered=staged.copy(); altered[off]^=1
            with self.assertRaises(ValueError): runner.sb2.zero.validate_staged(altered,before,data)

    def test_failed_preflight_never_runs_cycle_and_capture_uses_new_elf(self):
        port=Mock(); port.is_open=True; uart=Mock(); uart.lines=[]
        before=runner.baseline(); row={}
        with patch.object(runner,'stage_receipt',return_value=(runner.BASE,before)), \
                patch.object(runner.sb2.prior,'open_port',return_value=port), \
                patch.object(runner.sb2.prior,'JournalConsole',return_value=uart), \
                patch.object(runner.sb2.prior,'checkpoint'),patch.object(runner,'debug'), \
                patch.object(runner.sb2.prior,'wait_health_confirmation',side_effect=RuntimeError('preflight failed')), \
                patch.object(runner.cycle.fsm,'execute') as motion, \
                patch.object(runner.sb2,'capture_stopped') as capture:
            with self.assertRaisesRegex(RuntimeError,'preflight failed'):
                runner.execute(row,'mock',runner.BASE,runner.image())
            motion.assert_not_called()
            capture.assert_called_once_with(row,'mock',before,elf=runner.ELF)
            port.close.assert_called_once()


if __name__=='__main__': unittest.main()
