"""Offline tests only; never connect to hardware or read private captures."""
import struct
import unittest
from unittest.mock import patch
from pathlib import Path
import zlib

import foc_startup_evidence_stage as stage


def capture():
    raw = bytearray(b'\xff' * 0x80000)
    body = struct.pack('<11I', *stage.META[:11])
    raw[0x7E800:0x7E830] = body + struct.pack('<I', zlib.crc32(body))
    return raw


class StartupStageTests(unittest.TestCase):
    def test_pinned_candidate(self):
        data = stage.pinned_image()
        self.assertEqual(len(data), 211004)
        self.assertEqual(stage.image_info(data)[0], 'A')
        with patch.object(stage, 'SHA', '0' * 64):
            with self.assertRaises(RuntimeError):
                stage.pinned_image()

    def test_default_is_offline(self):
        with patch('sys.argv', ['stage']), patch.object(stage, 'debug') as hw:
            with patch.object(stage, 'load_baseline') as private:
                stage.main()
                hw.assert_not_called()
                private.assert_not_called()

    def test_requires_off_before_hardware(self):
        with patch('sys.argv', ['stage', '--allow-inactive-a-stage']):
            with patch.object(stage, 'debug') as hw:
                with patch.object(stage, 'load_baseline') as private:
                    with self.assertRaises(SystemExit):
                        stage.main()
                    hw.assert_not_called()
                    private.assert_not_called()

    def test_commands_only_program_a_and_never_resume(self):
        commands = stage.stage_commands(Path('pre.bin'), Path('before.bin'), Path('after.bin'))
        writes = [c for c in commands if c.startswith('flash ')]
        self.assertEqual(writes, [f'flash write_image erase {{{stage.IMAGE.as_posix()}}} 0x08008000 bin'])
        self.assertLess(commands.index('reset halt'), commands.index(writes[0]))
        self.assertTrue(any('Live Flash changed' in c for c in commands[:commands.index('reset halt')]))
        for command in commands:
            self.assertNotIn('reset run', command)
            self.assertFalse(command.startswith('resume'))
            self.assertNotIn('0x2001FFC0', command)
            self.assertNotIn('START_TRIAL', command)

    def test_full_readback_protects_every_byte_outside_a(self):
        image = stage.pinned_image()
        before = capture()
        after = before.copy()
        after[0x8000:0x8000 + len(image)] = image
        self.assertTrue(stage.verify_staged(before, after, image)['staged'])
        for address in (0, 0x7FFF, 0x40000, 0x77FFF, 0x78000, 0x7E800, 0x7F800, 0x7FFFF):
            bad = after.copy()
            bad[address] ^= 1
            with self.assertRaises(RuntimeError, msg=hex(address)):
                stage.verify_staged(before, bad, image)
        bad = after.copy()
        bad[0x8008] ^= 1
        with self.assertRaises(RuntimeError):
            stage.verify_staged(before, bad, image)


if __name__ == '__main__':
    unittest.main()
