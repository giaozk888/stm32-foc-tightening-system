import importlib.util
from pathlib import Path
import struct
import unittest
import zlib

spec = importlib.util.spec_from_file_location("can_fd_restore_original",
    Path(__file__).resolve().parents[1] / "tools/can_fd_restore_original_slot.py")
restore = importlib.util.module_from_spec(spec)
spec.loader.exec_module(restore)


class MetadataTest(unittest.TestCase):
    @staticmethod
    def record(generation):
        data = struct.pack("<11I", 0x424f4f54, 3, 1, 0, 0, generation, 100, 1, 100, 1, 0)
        return data + struct.pack("<I", zlib.crc32(data))

    def test_crc_protected_newest_selected(self):
        data = bytearray(b"\xff" * 0x80000)
        data[0x7e800:0x7e830] = self.record(308)
        data[0x7f000:0x7f030] = self.record(309)
        self.assertEqual(restore.latest_meta(data)[5], 309)
        data[0x7f02f] ^= 1
        self.assertEqual(restore.latest_meta(data)[5], 308)

    def test_no_valid_metadata_rejected(self):
        with self.assertRaises(RuntimeError):
            restore.latest_meta(b"\xff" * 0x80000)


if __name__ == "__main__":
    unittest.main()
