"""Compact board-runner checks with synthetic/mocked data; never board/private I/O."""
import copy
from pathlib import Path
import struct
import unittest
from unittest.mock import Mock, patch
import zlib

import zero_compact_board_test as tool


def sample(now=0, count=10000):
    return dict(host_time=now,
        state=dict(STATE='1', ARMED='1', FLAGS='0', FAULT='0', SD='0', MOE='0', CCER='0'),
        zero=dict(STATE='3', REASON='0', N='4000'),
        robust=dict(SEGMENTS='8', FLAGS='0', MAX='OFF', SEG_MAX='OFF', HARD_OFF='1'),
        policy=dict(DIAGNOSTIC='1', HARD_OFF='1', BURST='ALL_REJECTED', BLOCK='5', DELTA='40', PAIR='U_OR_V'),
        filter=dict(ADAPT='1', HARD_OFF='1'), ram=dict(ENABLED='1', HARD_OFF='1', DEADLINE_US='50'),
        compact=dict(ENABLED='1', HARD_OFF='1', FIXED_OPS='1', GUARD_US='25', DEADLINE_US='50'),
        timing=dict(WORK=str(count), MAX_US='40', LATE='0', OUTER=str(count // 20)),
        adc=dict(DWT='1', MISS='0', PF='0', LATE='0', MAX_CYC='8000', PAIRS=str(count)),
        fault=dict(VALID='0'), status=dict(FLT='0'),
        buffer=dict(STK_VALID='1', FREE_B='1024', DONE=str(count // 256)),
        encoder=dict(dma=dict(FAIL='0', TIMEOUT='0', IO='0', SCHED='0', STALE='0')))


class CompactBoardRunnerTests(unittest.TestCase):
    def test_default_no_hardware_or_private_access(self):
        with patch('sys.argv', ['test']), patch.object(tool, 'load_before') as private, \
             patch.object(tool.base, 'debug') as hardware:
            tool.main()
        private.assert_not_called()
        hardware.assert_not_called()

    def test_pinned_new_image_and_wrong_hash_rejected(self):
        self.assertEqual(len(tool.pinned_image()), 208228)
        with patch.object(tool, 'SHA', tool.base.SHA), self.assertRaises(RuntimeError):
            tool.pinned_image()

    def test_stage_only_exact_new_a_no_activation(self):
        cmds = tool.stage_commands(Path('live.bin'), Path('before.bin'), Path('after.bin'))
        writes = [c for c in cmds if c.startswith('flash write_image')]
        self.assertEqual(len(writes), 1)
        self.assertIn('ZeroAllRejectedCompact/foc2.bin', writes[0])
        self.assertTrue(writes[0].endswith('0x08008000 bin'))
        self.assertNotIn('reset run', cmds)
        self.assertFalse(any(c.startswith('resume') or '0x2001FFC0' in c for c in cmds))

    def test_single_normal_trial_mailbox_uses_new_image_crc(self):
        cmds = tool.trial_commands(Path('live.bin'), Path('staged.bin'))
        self.assertEqual(cmds.count('reset run'), 1)
        self.assertFalse(any(c.startswith('flash ') for c in cmds))
        image = tool.pinned_image()
        self.assertTrue(any(c.lower().startswith('mww 0x2001ffd4 ') and
                            int(c.split()[-1], 0) == len(image) for c in cmds))
        self.assertTrue(any(c.lower().startswith('mww 0x2001ffd8 ') and
                            int(c.split()[-1], 0) == zlib.crc32(image) for c in cmds))

    def test_no_motion_console(self):
        uart = tool.Console.__new__(tool.Console)
        for cmd in ('START', 'MOTOR TEST SPEED', 'FW END', 'BOOT A', 'FAULT CLEAR'):
            with self.assertRaises(ValueError):
                uart.query(cmd)

    def test_full_readback_protects_b_boot_and_metadata(self):
        before = bytearray(b'\xff' * 0x80000)
        body = struct.pack('<11I', *tool.META[:11])
        before[0x7E800:0x7E830] = body + struct.pack('<I', zlib.crc32(body))
        data = tool.pinned_image()
        actual = before.copy()
        actual[0x8000:0x8000 + len(data)] = data
        tool.base.unchanged_except_a(before, actual, data)
        for address in (0, 0x7FFF, 0x40000, 0x78000, 0x7E800, 0x7F800, 0x7FFFF):
            bad = actual.copy()
            bad[address] ^= 1
            with self.assertRaises(RuntimeError):
                tool.base.unchanged_except_a(before, bad, data)

    def test_acceptance_keeps_50us_adc_fault_encoder_gates(self):
        good = sample()
        tool.validate_sample(good)
        for key, field, value in (('timing', 'MAX_US', '50'), ('timing', 'LATE', '1'),
                ('adc', 'MAX_CYC', '8500'), ('adc', 'MISS', '1'), ('adc', 'LATE', '1'),
                ('compact', 'FIXED_OPS', '0'), ('compact', 'HARD_OFF', '0'),
                ('zero', 'N', '3999'), ('fault', 'VALID', '1'), ('buffer', 'FREE_B', '255')):
            bad = copy.deepcopy(good)
            bad[key][field] = value
            with self.assertRaises(RuntimeError):
                tool.validate_sample(bad)
        bad = copy.deepcopy(good)
        bad['encoder']['dma']['TIMEOUT'] = '1'
        with self.assertRaises(RuntimeError):
            tool.validate_sample(bad)

    def test_30_seconds_and_all_counters_must_advance(self):
        first, last = sample(), sample(30.01, 610000)
        tool.validate_progress(first, last)
        short = sample(29.99, 610000)
        with self.assertRaises(RuntimeError):
            tool.validate_progress(first, short)
        for key, field in (('timing', 'WORK'), ('timing', 'OUTER'), ('adc', 'PAIRS'), ('buffer', 'DONE')):
            bad = copy.deepcopy(last)
            bad[key][field] = first[key][field]
            with self.assertRaises(RuntimeError):
                tool.validate_progress(first, bad)

    def test_finally_always_saves_uart_and_closes_port(self):
        port, uart, row = Mock(is_open=True), Mock(lines=['record']), {}
        with patch.object(tool, 'load_stage', return_value=(Path('stage.bin'), bytes(0x80000))), \
             patch.object(tool.base, 'open_port', return_value=port), \
             patch.object(tool, 'Console', return_value=uart), \
             patch.object(tool.base, 'debug', side_effect=RuntimeError('trial')), \
             patch.object(tool.base, 'emergency_off', side_effect=RuntimeError('capture')):
            with self.assertRaisesRegex(RuntimeError, 'capture'):
                tool.trial(row, 'offline', tool.pinned_image(), Path('stage.json'))
        port.close.assert_called_once()
        self.assertEqual(row['uart'], ['record'])


if __name__ == '__main__':
    unittest.main()
