"""Staging harness regression; never accesses devices or private captures."""
from pathlib import Path
import unittest
from unittest.mock import patch

import rc_protected_board_test as stage


class ProtectedStageTests(unittest.TestCase):
    def test_exact_protected_image(self):
        self.assertEqual(len(stage.pinned_image()), stage.SIZE)

    def test_inspection_has_no_target_writes(self):
        for cmd in stage.inspect_commands(Path('live.bin'), Path('baseline.bin')):
            self.assertFalse(cmd.startswith(('halt', 'reset ', 'resume', 'flash ', 'mww ', 'mmw ')))

    def test_exact_compare_before_only_inactive_b_write_and_never_runs(self):
        commands = stage.stage_commands(Path('live.bin'), Path('baseline.bin'), Path('stage.bin'))
        combined = '\n'.join(commands)
        self.assertLess(combined.index('CPU not already halted'), combined.index('Live Flash changed'))
        self.assertLess(combined.index('Live Flash changed'), combined.index('reset halt'))
        self.assertLess(combined.index('reset halt'), combined.index('flash write_image'))
        writes = [c for c in commands if c.startswith('flash ')]
        self.assertEqual(len(writes), 1)
        self.assertTrue(writes[0].endswith('0x08040000 bin'))
        self.assertIn('verify_image', combined)
        for forbidden in ('reset run', 'resume', '0x2001FFC0', 'START', 'force_confirm'):
            self.assertNotIn(forbidden, combined)

    def test_full_capture_comparison_rejects_protected_region_changes(self):
        image = stage.pinned_image()
        before = bytes([0x55]) * 0x80000
        actual = bytearray(before)
        end = 0x40000 + len(image)
        page_end = (end + 0x7ff) & ~0x7ff
        actual[0x40000:end] = image
        actual[end:page_end] = b'\xff' * (page_end - end)
        with patch.object(stage, 'validate_baseline'), patch.object(stage, 'latest_meta', return_value=stage.META):
            stage.compare_stage(before, actual, image)
            for offset in (0, 0x7fff, 0x8000, 0x3ffff, page_end, 0x78000, 0x7e800, 0x7f800):
                changed = actual.copy()
                changed[offset] ^= 1
                with self.subTest(offset=offset), self.assertRaises(ValueError):
                    stage.compare_stage(before, changed, image)

    def test_incomplete_or_changed_baseline_rejected(self):
        with self.assertRaises(ValueError):
            stage.validate_baseline(bytes(0x80000))
        with self.assertRaises(ValueError):
            stage.validate_baseline(b'')


if __name__ == '__main__':
    unittest.main()
