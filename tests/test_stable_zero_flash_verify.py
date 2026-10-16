"""Pure memory tests; no hardware or filesystem capture."""
import sys
import struct
import unittest
import zlib
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/"tools"))
from stable_zero_flash_verify import verify

IMAGE = struct.pack("<II", 0x2001FFF8, 0x08008009)+bytes(range(64))
def flash(confirmed=2):
    data = bytearray(0x80000)
    words = (0x424F4F54, 3, confirmed, 0, 0, 346 if confirmed == 2 else 348,
        0 if confirmed == 2 else len(IMAGE), 0 if confirmed == 2 else zlib.crc32(IMAGE),
        100, 1234, 0)
    packet = struct.pack("<11I", *words)
    data[0x7E800:0x7E830] = packet+struct.pack("<I", zlib.crc32(packet))
    data[0x8000:0x8000+len(IMAGE)] = IMAGE
    return data

class FlashCompareTests(unittest.TestCase):
    def test_stage_exact_and_metadata_unchanged(self):
        result = verify(flash(), flash(), IMAGE, True)
        self.assertTrue(all(result["protected_regions_unchanged"].values()))
        self.assertEqual(result["confirmed_slot"], 2)
        with self.assertRaises(RuntimeError):
            verify(flash(), flash(1), IMAGE, True)

    def test_confirmed_crc_and_size(self):
        self.assertEqual(verify(flash(), flash(1), IMAGE)["confirmed_slot"], 1)
        with self.assertRaises(RuntimeError):
            verify(flash(), flash(), IMAGE)

    def test_failed_a_retired_and_b_preserved(self):
        self.assertTrue(verify(flash(), flash(), IMAGE, rolled_back=True)["rolled_back"])
        with self.assertRaises(RuntimeError):
            verify(flash(), flash(1), IMAGE, rolled_back=True)
        with self.assertRaises(ValueError):
            verify(flash(), flash(), IMAGE, staged=True, rolled_back=True)

    def test_each_protected_region_and_app_bytes_rejected(self):
        for address in (0, 0x8000, 0x40000, 0x78000, 0x7E700, 0x7F800, 0x7FFFF):
            changed = flash(1)
            changed[address] ^= 1
            with self.subTest(address=hex(address)), self.assertRaises(RuntimeError):
                verify(flash(), changed, IMAGE)

if __name__ == "__main__":
    unittest.main()
