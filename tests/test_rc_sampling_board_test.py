"""Offline regression for the RC stage harness; no hardware/private access."""
from pathlib import Path
import unittest
from unittest.mock import patch

import rc_sampling_board_test as stage


class RcStageTests(unittest.TestCase):
    def test_exact_power_hard_off_image(self):
        self.assertEqual(len(stage.pinned_image()), stage.SIZE)

    def test_stage_gate_precedes_flash_write_and_never_runs(self):
        commands = stage.stage_commands(Path('live.bin'), Path('before.bin'), Path('after.bin'))
        combined = '\n'.join(commands)
        self.assertIn('0x8040000', combined)
        self.assertLess(combined.index('Live Flash changed'), combined.index('reset halt'))
        self.assertLess(combined.index('reset halt'), combined.index('flash write_image'))
        writes = [c for c in commands if c.startswith('flash ')]
        self.assertEqual(len(writes), 1)
        self.assertTrue(writes[0].endswith('0x08008000 bin'))
        for forbidden in ('reset run', 'resume', '0x2001FFC0', 'force_confirm', 'START'):
            self.assertNotIn(forbidden, combined)

    def test_inspection_is_read_only(self):
        commands = stage.inspect_commands(Path('live.bin'), Path('before.bin'))
        for command in commands:
            self.assertFalse(command.startswith(('mww ', 'mmw ', 'reset ', 'resume', 'flash ', 'halt')))

    def test_explicit_debug_halt_never_resets_or_writes(self):
        commands = stage.halt_inspect_commands(Path('live.bin'), Path('before.bin'))
        self.assertEqual(commands.count('halt'), 1)
        self.assertIn('0x8040000', '\n'.join(commands[:commands.index('halt')]))
        for command in commands:
            self.assertFalse(command.startswith(('mww ', 'mmw ', 'reset ', 'resume', 'flash ')))

    def test_compare_rejects_any_outside_a_page_change(self):
        image = stage.pinned_image()
        before = bytes([0x55]) * 0x80000
        actual = bytearray(before)
        end = 0x8000 + len(image)
        page_end = (end + 0x7ff) & ~0x7ff
        actual[0x8000:end] = image
        actual[end:page_end] = b'\xff' * (page_end - end)
        with patch.object(stage, 'validate_baseline'), patch.object(stage, 'latest_meta', return_value=stage.META):
            stage.compare_stage(before, actual, image)
            for offset in (0, 0x7fff, page_end, 0x40000, 0x78000, 0x7e800, 0x7f800):
                changed = actual.copy()
                changed[offset] ^= 1
                with self.subTest(offset=offset), self.assertRaises(ValueError):
                    stage.compare_stage(before, changed, image)

    def test_wrong_baseline_never_accepted(self):
        with self.assertRaises(ValueError):
            stage.validate_baseline(bytes(0x80000))


if __name__ == '__main__':
    unittest.main()
