"""Offline tests; no device or private backup access."""
from pathlib import Path
import struct
import unittest
from unittest.mock import patch
import zlib

import rc_sampling_trial as trial


class RcTrialTests(unittest.TestCase):
    def test_mailbox_b_to_a_binds_exact_image(self):
        image = trial.stage.pinned_image()
        words = trial.mailbox(image)
        self.assertEqual(words[:5], (0x584F424D, 1, 2, 2, 1))
        self.assertEqual(words[5:7], (len(image), zlib.crc32(image)))
        self.assertEqual(words[7], zlib.crc32(struct.pack('<7I', *words[:7])))
        with self.assertRaises(ValueError):
            trial.mailbox(image[:-1])

    def test_one_reset_run_after_compare_and_sram_request(self):
        commands = trial.trial_commands(Path('live.bin'), Path('before.bin'), trial.stage.pinned_image())
        self.assertEqual(commands.count('reset run'), 1)
        all_commands = '\n'.join(commands)
        self.assertLess(all_commands.index('Live Flash changed'), all_commands.index('mww 0x2001FFC0'))
        self.assertLess(all_commands.index('mww 0x2001FFC0'), all_commands.index('reset run'))
        self.assertFalse(any(c.startswith('flash ') for c in commands))
        self.assertFalse(any(c.startswith('resume') for c in commands))
        self.assertEqual(commands[-1], 'shutdown')

    def test_console_rejects_motion_and_trial_uart(self):
        uart = trial.Console(None)
        for command in ('START', 'MOTOR TEST SPEED', 'MOTOR TEST STOP', 'FW END',
                        'RESET', 'FAULT CLEAR', 'XFER ENGINE CLOSE'):
            with self.subTest(command=command), self.assertRaises(ValueError):
                uart.query(command)
        self.assertEqual(uart.starts, 0)
        self.assertEqual(uart.ends, 0)

    def test_final_compare_rejects_nonmetadata_changes(self):
        # No private baseline needed for boundary validation.
        before = bytes(0x80000)
        for offset in (0, 0x8000, 0x40000, 0x78000, 0x7f800):
            actual = bytearray(before)
            actual[offset] = 1
            with self.subTest(offset=offset), self.assertRaises(RuntimeError):
                trial.compare_final(before, actual, trial.stage.pinned_image())

    def test_coarse_bottom_alarm_is_not_relabelled_50us_or_sample_loss(self):
        row = {'timing': {}, 'cost': {}, 'late_frame': {},
               'adc': {'MAX_CYC': '7476', 'LATE': '26961', 'MISS': '0'}}
        with patch.object(trial, 'timing'), patch.object(trial, 'validate_cost'), \
                patch.object(trial, 'validate_late'):
            trial.validate_50us(row)
            row['adc']['MAX_CYC'] = '8500'
            with self.assertRaises(RuntimeError):
                trial.validate_50us(row)


if __name__ == '__main__':
    unittest.main()
