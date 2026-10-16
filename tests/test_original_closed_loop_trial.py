"""Offline guards only; no serial port, debugger or motion operations."""
import struct
import sys
import unittest
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import original_closed_loop_trial as trial


class TrialGuards(unittest.TestCase):
    def test_packet_is_trial_not_force_confirmation(self):
        words = trial.mailbox(trial.stage.IMAGE.read_bytes())
        self.assertEqual(words[:6], (0x584F424D, 1, 2, 1, 2, 199056))
        self.assertEqual(words[6], 0xD4682905)
        self.assertEqual(words[7], zlib.crc32(struct.pack('<7I', *words[:7])))

    def test_modified_image_rejected(self):
        image = bytearray(trial.stage.IMAGE.read_bytes())
        image[-1] ^= 1
        with self.assertRaises(RuntimeError):
            trial.mailbox(image)

    def test_halted_output_gate(self):
        output = ('0xE000ED08 : 08000000\n0xE000EDF0 : 00020003\n'
                  '0x48000814 : 00000000\n0x40012C44 : 00000000\n'
                  '0x40012C00 : 00000000\n0x40012C20 : 00000000\n')
        trial.require_halted_off(output)
        for before, after in (('00020003', '00000003'), ('08000000', '08008000'),
                              ('0x48000814 : 00000000', '0x48000814 : 00000040'),
                              ('0x40012C20 : 00000000', '0x40012C20 : 00000001'),
                              ('0x40012C44 : 00000000', '0x40012C44 : 00004000')):
            with self.subTest(after=after), self.assertRaises(RuntimeError):
                trial.require_halted_off(output.replace(before, after))

    def test_ready_requires_confirmed_healthy_idle_b(self):
        lines = ('1 OK FW CURRENT=B CONFIRMED=B PENDING=- ATTEMPTS=0 ACTIVE=0',
                 '2 OK SELFTEST READY=1 MASK=0x000',
                 '3 OK STATUS MODE=IDLE BUSY=0 FLT=0',
                 '4 OK ANALOG SAFE LATCHED=0')
        trial.require_ready(*lines)
        for index, before, after in ((0, 'CONFIRMED=B', 'CONFIRMED=A'),
            (0, 'PENDING=-', 'PENDING=B'), (1, 'READY=1', 'READY=0'),
            (2, 'FLT=0', 'FLT=1'), (2, 'BUSY=0', 'BUSY=1'),
            (3, 'LATCHED=0', 'LATCHED=1')):
            modified = list(lines)
            modified[index] = modified[index].replace(before, after)
            with self.subTest(after=after), self.assertRaises(RuntimeError):
                trial.require_ready(*modified)

    def test_console_never_accepts_motion_as_probe_or_cleanup(self):
        console = trial.Console(None)
        for command in ('START', 'CLEAR', 'FW END', 'BOOT B'):
            with self.subTest(command=command), self.assertRaises(ValueError):
                console.query(command)
            with self.subTest(command=command), self.assertRaises(ValueError):
                console.cleanup_command(command)


if __name__ == '__main__':
    unittest.main()
