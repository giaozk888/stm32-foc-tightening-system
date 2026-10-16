"""Offline contracts only. No probe, UART, Flash or motor operations."""
import hashlib
from pathlib import Path
import struct
import sys
import unittest
import zlib

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import phase_current_4a_stage as tool


class StageTests(unittest.TestCase):
    def test_exact_b_image(self):
        _, image = tool.target_image()
        self.assertEqual(tool.image_info(image)[0], "B")
        self.assertEqual(hashlib.sha256(image).hexdigest(), tool.TARGET_SHA)

    def test_activation_motion_sampling_and_reset_commands_rejected(self):
        uart = tool.StageOnlyUart.__new__(tool.StageOnlyUart)
        for text in ("FW END", "FW CONFIRM", "FW ABORT", "BOOT B", "START",
                     "CLEAR", "ZERO SAMPLE", "ADC PAR SAMPLE ON", "BENCH RUN"):
            with self.subTest(text=text), self.assertRaises(ValueError):
                uart.command(text)
            with self.subTest(query=text), self.assertRaises(ValueError):
                uart.query(text)

    def test_baseline_only_confirmed_exact_locked_a(self):
        a = (tool.ROOT / "foc2_app_a/build/ZeroInjectedControlOff20261012/foc2.bin").read_bytes()
        b = (tool.ROOT / "foc2_app_b/build/AdcPinsLowDouble20261011/foc2.bin").read_bytes()
        data = bytearray(b"\xff" * 0x80000)
        data[0x8000:0x8000+len(a)] = a
        data[0x40000:0x40000+len(b)] = b

        def meta(confirmed=1, pending=0):
            words = [0x424F4F54, 3, confirmed, pending, 0, 405,
                     len(a), zlib.crc32(a), len(b), zlib.crc32(b), 0]
            payload = struct.pack("<11I", *words)
            data[0x7F000:0x7F030] = payload + struct.pack("<I", zlib.crc32(payload))

        meta()
        self.assertEqual(tool.baseline(data)["current"], "A")
        meta(2)
        with self.assertRaises(RuntimeError):
            tool.baseline(data)
        meta(1, 2)
        with self.assertRaises(RuntimeError):
            tool.baseline(data)
        meta()
        data[0x8010] ^= 1
        with self.assertRaises(RuntimeError):
            tool.baseline(data)

    def test_staged_status_requires_uncommitted_same_a_and_exact_size_crc(self):
        _, image = tool.target_image()
        _, crc = tool.image_info(image)
        good = (f"1 OK FW CURRENT=A CONFIRMED=A TARGET=B PENDING=- ATTEMPTS=0 "
                f"GEN=405 ACTIVE=1 RX={len(image)} SIZE={len(image)} EXPECT=0x{crc:08X}")
        tool.require_staged(good, 405, image)
        for old, new in (("CURRENT=A", "CURRENT=B"), ("CONFIRMED=A", "CONFIRMED=B"),
                         ("PENDING=-", "PENDING=B"), ("GEN=405", "GEN=406"),
                         ("ACTIVE=1", "ACTIVE=0"), ("TARGET=B", "TARGET=A"),
                         (f"RX={len(image)}", "RX=10")):
            with self.subTest(new=new), self.assertRaises(RuntimeError):
                tool.require_staged(good.replace(old, new), 405, image)

    def test_private_backup_before_stage_and_no_activation(self):
        source = Path(tool.__file__).read_text(encoding="utf-8")
        self.assertIn("allow_reset=False", source)
        self.assertNotIn('uart.command("FW END"', source)
        self.assertNotIn('cli("-rst"', source)
        self.assertLess(source.index('"/inheritance:r"'), source.index('before = capture("before")'))
        self.assertLess(source.index('before = capture("before")'), source.index('stage(uart,'))
        self.assertIn('before[:0x40000] != after[:0x40000]', source)


if __name__ == "__main__":
    unittest.main()
