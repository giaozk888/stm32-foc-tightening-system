"""Offline checks only: no UART, SWD, reset or firmware write."""
import hashlib
import struct
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from bounded_speed_stage import baseline, validate_profile
from test_zero_retest_deploy import meta


class SpeedStageTest(unittest.TestCase):
    image_a = struct.pack("<II", 0x2001FFC0, 0x08008009) + bytes(64)

    def capture(self, confirmed=1):
        data = bytearray(b"\xff" * 0x80000)
        data[0x8000:0x8000 + len(self.image_a)] = self.image_a
        meta(data, confirmed, a=self.image_a)
        return data

    def test_exact_confirmed_locked_a_baseline(self):
        with patch("bounded_speed_stage.PINNED_A", hashlib.sha256(self.image_a).hexdigest()):
            self.assertEqual(baseline(self.capture())["confirmed"], "A")

    def test_wrong_slot_or_changed_active_image_is_rejected(self):
        with patch("bounded_speed_stage.PINNED_A", hashlib.sha256(self.image_a).hexdigest()):
            with self.assertRaises(RuntimeError):
                baseline(self.capture(2))
            data = self.capture()
            data[0x8040] ^= 1
            with self.assertRaises(RuntimeError):
                baseline(data)

    def test_unknown_hash_is_rejected_even_with_matching_crc(self):
        with patch("bounded_speed_stage.PINNED_A", "0" * 64):
            with self.assertRaises(RuntimeError):
                baseline(self.capture())

    def test_current_normal_build_and_hash_gate(self):
        path = Path(__file__).resolve().parents[1] / "foc2_app_b/build/PoweredSpeedBounded20261009/foc2.bin"
        if not path.exists():
            self.skipTest("Build the bounded-speed B profile before artifact validation")
        image = path.read_bytes()
        self.assertEqual(validate_profile(path, hashlib.sha256(image).hexdigest()), image)
        with self.assertRaises(RuntimeError):
            validate_profile(path, "0" * 64)


if __name__ == "__main__":
    unittest.main()
