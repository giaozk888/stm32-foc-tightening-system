"""Offline deployment gates. Does not open probes or ports."""
import struct
import sys
import unittest
import zlib
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from zero_retest_deploy import require_service, require_confirmed, compare_flash, DiagnosticUart

def meta(data, slot, a=None, b=None):
    words = [0x424F4F54, 3, slot, 0, 0, 1, 0, 0, 0, 0, 0]
    if a: words[6:8] = [len(a), zlib.crc32(a)]
    if b: words[8:10] = [len(b), zlib.crc32(b)]
    payload = struct.pack("<11I", *words)
    data[0x7F000:0x7F030] = payload + struct.pack("<I", zlib.crc32(payload))

class DeploymentTests(unittest.TestCase):
    def test_every_gate_is_required(self):
        good = "OK PROFILE=LOCKED_DIAGNOSTIC LOCK=1 SD=0 MOE=0 CCER=0 CEN=0 FOC=0 MOTOR_READY=0 IF=0 ACTIVE=0"
        require_service(good)
        for token in good.split()[1:]:
            with self.subTest(token=token), self.assertRaises(RuntimeError):
                require_service(good.replace(token, token.split("=")[0] + "=INVALID"))
        require_confirmed("OK CURRENT=A CONFIRMED=A PENDING=- ATTEMPTS=0 ACTIVE=0", "A")
        with self.assertRaises(RuntimeError):
            require_confirmed("OK CURRENT=A CONFIRMED=B PENDING=A ATTEMPTS=1 ACTIVE=0", "A")

    def test_both_slots_protect_original_opposite_and_data(self):
        for slot in "AB":
            start = 0x8000 if slot == "A" else 0x40000
            image = struct.pack("<II", 0x2001FFC0, 0x08000000 + start + 9) + bytes(64)
            before = bytearray(b"\xff" * 0x80000)
            meta(before, 2 if slot == "A" else 1)
            actual = bytearray(before)
            actual[start:start + len(image)] = image
            compare_flash(before, actual, image, slot, staged=True)
            for protected in (0, 0x78000, 0x7F800, 0x40000 if slot == "A" else 0x8000):
                corrupt = bytearray(actual)
                corrupt[protected] ^= 1
                with self.assertRaises(RuntimeError):
                    compare_flash(before, corrupt, image, slot, staged=True)
            meta(actual, 1 if slot == "A" else 2, a=image if slot == "A" else None,
                 b=image if slot == "B" else None)
            compare_flash(before, actual, image, slot)

    def test_read_only_uart_never_sends_sampling_or_motion(self):
        class Port:
            def write(self, value): raise AssertionError("Must not reach UART")
        uart = DiagnosticUart(Port())
        for command in ("START", "CLEAR", "ZERO SAMPLE", "FW END", "BOOT B", "FW CONFIRM"):
            with self.assertRaises(ValueError): uart.query(command)

if __name__ == "__main__":
    unittest.main()
