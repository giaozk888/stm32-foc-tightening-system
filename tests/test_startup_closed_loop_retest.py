"""Offline pinned deployment, command and export checks; never board access."""
import struct
import subprocess
import sys
import unittest
from unittest.mock import patch

import startup_closed_loop_retest as tool


class RetestTests(unittest.TestCase):
    def test_exact_b_and_single_normal_trial(self):
        image = tool.pinned_image()
        self.assertEqual(len(image), 210116)
        words = tool.trial_words()
        self.assertEqual(words[:5], (0x584F424D, 1, 2, 1, 2))
        self.assertEqual(words[5:7], (len(image), tool.zlib.crc32(image)))
        self.assertEqual(words[7], tool.zlib.crc32(struct.pack('<7I', *words[:7])))
        self.assertEqual(tool.META[2:6], (1, 0, 0, 558))

    def test_stage_only_b_never_resume_or_mutate_metadata(self):
        path = tool.base.old.ROOT/'tests/foc_adaptive_build/mock.bin'
        commands = tool.stage_commands(path, path, path)
        writes = [c for c in commands if c.startswith('flash ')]
        self.assertEqual(len(writes), 1)
        self.assertTrue(writes[0].endswith(' 0x08040000 bin'))
        self.assertNotIn('reset run', commands)
        self.assertNotIn('resume', commands)
        self.assertFalse(any(c.startswith('mww 0x080') for c in commands))
        trial = tool.activation_commands(path, path)
        self.assertEqual(trial.count('reset run'), 1)
        self.assertFalse(any(c.startswith('flash ') or c.startswith('mww 0x080') for c in trial))

    def test_independent_stage_compare_rejects_protected_changes(self):
        before = bytearray(b'\xff' * 0x80000)
        before[0x7E800:0x7E800+48] = struct.pack('<12I', *tool.META)
        image = tool.pinned_image()
        actual = bytearray(before)
        actual[0x40000:0x40000+len(image)] = image
        self.assertTrue(tool.verify_stage(bytes(before), bytes(actual), image))
        for offset in (0, 0x8000, 0x3ffff, 0x78000, 0x7F800, 0x7FFFF, 0x40010):
            wrong = bytearray(actual)
            wrong[offset] ^= 1
            with self.assertRaises((ValueError, RuntimeError)):
                tool.verify_stage(bytes(before), bytes(wrong), image)

    def test_cli_requires_physical_state_before_private_or_hardware(self):
        for argv in (['--stage-b'], ['--trial-from', 'anything.json']):
            result = subprocess.run([sys.executable, str(tool.base.old.ROOT/'tools/startup_closed_loop_retest.py'),
                                     *argv], capture_output=True, text=True)
            self.assertEqual(result.returncode, 2)
            self.assertIn('Actual physical state required', result.stderr)

    def test_no_generic_motion_reset_clear_on_diagnostic_console(self):
        class Fake:
            READ = tool.Console.READ
        for command in ('START', 'FW END', 'RESET', 'MOTOR TEST SPEED', 'CLEAR', 'SAVE', 'SET RUNDOWN_RPM 80'):
            with self.assertRaises(ValueError):
                tool.Console.query(Fake(), command)

    def test_frozen_trace_export_and_partial_evidence(self):
        class Fake:
            def __init__(self):
                self.commands = []
            def query(self, command):
                self.commands.append(command)
                if command.endswith('CONFIG'):
                    return 'OK STARTUP CONFIG ENABLED=1 ROWS=32 FIRST_CAUSE=1 BYTES=2000'
                if command == 'MOTOR TEST STARTUP':
                    return 'OK STARTUP N=2 TOTAL=2 FROZEN=1 FAULT=1 FIRST_FLAGS=1024'
                if command.endswith('FAULT'):
                    return 'OK STARTUP FRAME US=30000 SEQ=500 RPM10=20,700,607'
                return 'OK STARTUP FRAME US=20000 SEQ=400 RPM10=20,300,200'
        fake, row = Fake(), {}
        tool.collect_trace(fake, row)
        self.assertTrue(row['startup_capture_complete'])
        self.assertEqual(len(row['startup_frames']), 2)
        self.assertEqual(fake.commands[-1], 'MOTOR TEST STARTUP')
        with patch.object(tool.evidence, 'trace_config', side_effect=ValueError('wrong identity')):
            with self.assertRaises(ValueError):
                tool.collect_trace(Fake(), {})


if __name__ == '__main__':
    unittest.main()
