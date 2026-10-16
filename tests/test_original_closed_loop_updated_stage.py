"""Offline staging gates, no probe/serial operations."""
import hashlib
from pathlib import Path
import struct
import sys
import unittest
from unittest.mock import patch
import zlib

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import original_closed_loop_updated_stage as stage


def fixture(confirmed=1, pending=0, attempts=0, b_size=0):
    raw = bytearray(b'\xff' * 0x80000)
    words = (0x424F4F54, 3, confirmed, pending, attempts, 540, 207972, 123, b_size, 0, 0)
    body = struct.pack('<11I', *words)
    struct.pack_into('<12I', raw, 0x7E800, *words, zlib.crc32(body))
    return raw


class StageGuards(unittest.TestCase):
    def test_exact_image(self):
        self.assertEqual(len(stage.pinned_image()), 200360)

    def test_halted_output_off_required(self):
        good = 'VTOR=0x8008000\nDHCSR=0x30003\nSD=0x0\nBDTR=0x2002055\nCCER=0x0\n'
        stage.check_off(good, (0x08008000,))
        for before, after in (('0x30003', '0x10003'), ('SD=0x0', 'SD=0x40'),
                              ('0x2002055', '0x200A055'), ('CCER=0x0', 'CCER=0x1'),
                              ('0x8008000', '0x8040000')):
            with self.subTest(after=after), self.assertRaises(RuntimeError):
                stage.check_off(good.replace(before, after), (0x08008000,))
        with self.assertRaises(RuntimeError):
            stage.check_off('', (0x08008000,))

    def test_inactive_b_and_exact_fallback_required(self):
        raw = fixture()
        digest = hashlib.sha256(raw[0x8000:0x8000 + 207972]).hexdigest()
        with patch.object(stage, 'A_SHA', digest):
            self.assertEqual(stage.validate_baseline(raw)[5], 540)
            for bad in (fixture(confirmed=2), fixture(pending=2), fixture(attempts=1),
                        fixture(b_size=200360), raw[:-1]):
                with self.assertRaises(RuntimeError):
                    stage.validate_baseline(bad)
            raw[0x9000] ^= 1
            with self.assertRaises(RuntimeError):
                stage.validate_baseline(raw)

    def test_stage_comparison_protects_all_non_b_bytes(self):
        image = stage.pinned_image()
        before = fixture()
        actual = bytearray(before)
        actual[0x40000:0x40000 + len(image)] = image
        stage.compare_flash(before, actual, image, 'B', staged=True)
        for offset in (0, 0x9000, 0x78000, 0x7F800):
            bad = bytearray(actual)
            bad[offset] ^= 1
            with self.subTest(offset=offset), self.assertRaises(RuntimeError):
                stage.compare_flash(before, bad, image, 'B', staged=True)

    def test_tool_has_no_activation_or_motion(self):
        source = Path(stage.__file__).read_text('utf-8')
        for forbidden in ('reset run', "'START'", "'FW END'", 'mww 0x2001FFC0',
                          'flash erase_address', 'mass_erase'):
            self.assertNotIn(forbidden, source)
        self.assertNotIn('verify_image ', source)
        self.assertIn('error "Live Flash changed"', source)
        self.assertIn('flash write_image erase {{{IMAGE.as_posix()}}} 0x08040000 bin', source)


if __name__ == '__main__':
    unittest.main()
