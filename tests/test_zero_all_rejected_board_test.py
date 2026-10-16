"""Offline checks only: no private data access and no physical board access."""
import struct
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
import zlib

import zero_all_rejected_board_test as tool


class AllRejectedBoardTests(unittest.TestCase):
    def test_default_has_no_hardware_or_private_reads(self):
        with patch('sys.argv', ['test']), patch.object(tool, 'load_before') as private:
            with patch.object(tool, 'debug') as hardware:
                tool.main()
                private.assert_not_called()
                hardware.assert_not_called()

    def test_image_pinned_and_hard_off(self):
        data = tool.pinned_image()
        self.assertEqual(len(data), 207444)
        with patch.object(tool, 'SHA', '0' * 64), self.assertRaises(RuntimeError):
            tool.pinned_image()

    def test_no_motion_console(self):
        uart = tool.Console.__new__(tool.Console)
        for cmd in ('START', 'MOTOR TEST SPEED', 'FW END', 'FAULT CLEAR', 'BOOT B'):
            with self.assertRaises(ValueError):
                uart.query(cmd)

    def test_stage_targets_only_unconfirmed_a_without_resume(self):
        commands = tool.stage_commands(Path('live.bin'), Path('prior.bin'), Path('staged.bin'))
        self.assertEqual(sum(c.startswith('flash write_image') for c in commands), 1)
        self.assertTrue(any(c.endswith('0x08008000 bin') for c in commands if c.startswith('flash ')))
        self.assertNotIn('reset run', commands)
        self.assertFalse(any(c.startswith('resume') for c in commands))
        self.assertFalse(any('0x2001FFC0' in c for c in commands))

    def test_trial_only_has_one_normal_request_and_no_programming(self):
        commands = tool.trial_commands(Path('live.bin'), Path('staged.bin'))
        self.assertEqual(commands.count('reset run'), 1)
        self.assertFalse(any(c.startswith('flash ') for c in commands))
        self.assertEqual(sum(c.startswith('mww 0x2001FFC0') for c in commands), 2)

    def test_final_metadata_requires_exact_confirmed_a(self):
        image = tool.pinned_image()
        meta = list(tool.META)
        meta[2:8] = (1, 0, 0, tool.META[5] + 4, len(image), zlib.crc32(image))
        tool.validate_confirmed_metadata(tuple(meta), image)
        for index, value in ((2, 2), (3, 1), (4, 1), (5, tool.META[5]), (6, 0), (7, 0), (8, 0)):
            bad = meta.copy()
            bad[index] = value
            with self.assertRaises(RuntimeError):
                tool.validate_confirmed_metadata(tuple(bad), image)

    def test_port_and_uart_saved_even_if_emergency_capture_fails(self):
        port = Mock(is_open=True)
        uart = Mock(lines=['diagnostic record'])
        row = {}
        with patch.object(tool, 'load_stage', return_value=(Path('staged.bin'), bytes(0x80000))), \
             patch.object(tool, 'open_port', return_value=port), \
             patch.object(tool, 'Console', return_value=uart), \
             patch.object(tool, 'debug', side_effect=RuntimeError('trial failed')), \
             patch.object(tool, 'emergency_off', side_effect=RuntimeError('capture failed')):
            with self.assertRaisesRegex(RuntimeError, 'capture failed'):
                tool.trial(row, 'offline', tool.pinned_image(), Path('receipt.json'))
        port.close.assert_called_once()
        self.assertEqual(row['uart'], ['diagnostic record'])

    def test_readback_preserves_b_bootloader_and_metadata(self):
        before = bytearray(b'\xff' * 0x80000)
        body = struct.pack('<11I', *tool.META[:11])
        before[0x7E800:0x7E830] = body + struct.pack('<I', zlib.crc32(body))
        data = tool.pinned_image()
        actual = before.copy()
        actual[0x8000:0x8000 + len(data)] = data
        tool.unchanged_except_a(before, actual, data)
        for address in (0, 0x7FFF, 0x40000, 0x77FFF, 0x78000, 0x7E800, 0x7F800, 0x7FFFF):
            bad = actual.copy()
            bad[address] ^= 1
            with self.assertRaises(RuntimeError):
                tool.unchanged_except_a(before, bad, data)

    def test_zero_requires_full_window_and_exact_diagnostic_policy(self):
        good = dict(state=dict(STATE='1', ARMED='1', FLAGS='0', FAULT='0', SD='0', MOE='0', CCER='0'),
            zero=dict(STATE='3', REASON='0', N='4000'),
            robust=dict(SEGMENTS='8', FLAGS='0', MAX='OFF', SEG_MAX='OFF', HARD_OFF='1'),
            policy=dict(DIAGNOSTIC='1', HARD_OFF='1', BURST='ALL_REJECTED', BLOCK='5', DELTA='40', PAIR='U_OR_V'),
            filter=dict(ADAPT='1', HARD_OFF='1'), ram=dict(ENABLED='1', HARD_OFF='1', DEADLINE_US='50'))
        tool.validate_zero(good)
        for key, field, value in (('zero', 'N', '2525'), ('policy', 'HARD_OFF', '0'),
                                  ('robust', 'FLAGS', '4'), ('state', 'SD', '1')):
            bad = {k: dict(v) for k, v in good.items()}
            bad[key][field] = value
            with self.assertRaises(RuntimeError):
                tool.validate_zero(bad)


if __name__ == '__main__':
    unittest.main()
