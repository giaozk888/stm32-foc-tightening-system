"""Pure offline gates; no probe, serial port or Flash operations."""
import struct
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
import hashlib
import zlib

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import zero_span100_acceptance as accept

GOOD = ("OK PROFILE=LOCKED_DIAGNOSTIC LOCK=1 SD=0 MOE=0 CCER=0 CEN=0 "
        "FOC=0 MOTOR_READY=0 IF=0 ACTIVE=0 SPAN=100 ADC_READY=1 "
        "STATE=0 REASON=0 ADC=0 N=0 SET=0")


class AcceptanceTests(unittest.TestCase):
    def test_new_service_is_explicit_and_unsampled(self):
        accept.require_new_service(GOOD)
        for token in GOOD.split()[1:]:
            with self.subTest(token=token), self.assertRaises(RuntimeError):
                accept.require_new_service(GOOD.replace(token, token.split("=")[0] + "=BAD"))
        with self.assertRaises(RuntimeError):
            accept.require_new_service(GOOD.replace(" SPAN=100", ""))

    def test_registers_off_and_fault_free(self):
        values = (accept.BASES["B"], 0, 0x02002055, 0x20, 0, 0)
        def render(items):
            return "\n".join(f"0x{a:08X} : {v:08X}" for a, v in zip(accept.ADDRESSES, items))
        accept.require_registers(render(values), "B")
        for index, bad in enumerate((accept.BASES["A"], 0x40, 0x0200A055, 0x21, 1, 1)):
            broken = list(values)
            broken[index] = bad
            with self.subTest(index=index), self.assertRaises(RuntimeError):
                accept.require_registers(render(broken), "B")
        with self.assertRaises(RuntimeError):
            accept.require_registers(render(values[:-1]), "B")

    def test_both_known_images_and_idle_metadata_required(self):
        images = {s: struct.pack("<II", 0x2001FFC0, b + 9) + bytes(64)
                  for s, b in accept.BASES.items()}
        pins = {s: hashlib.sha256(data).hexdigest() for s, data in images.items()}
        data = bytearray(b"\xff" * 0x80000)
        for slot, image in images.items():
            start = accept.BASES[slot] - 0x08000000
            data[start:start + len(image)] = image
        def metadata(pending=0, attempts=0):
            words = [0x424F4F54, 3, 2, pending, attempts, 356,
                     len(images["A"]), zlib.crc32(images["A"]),
                     len(images["B"]), zlib.crc32(images["B"]), 0]
            payload = struct.pack("<11I", *words)
            data[0x7F000:0x7F030] = payload + struct.pack("<I", zlib.crc32(payload))
        metadata()
        with patch.object(accept, "OLD_PINNED", pins):
            self.assertEqual(accept.locked_baseline(data)["current"], "B")
            for pending, attempts in ((1, 0), (0, 1)):
                metadata(pending, attempts)
                with self.assertRaises(RuntimeError):
                    accept.locked_baseline(data)
            metadata()
            data[0x800A] ^= 1
            with self.assertRaises(RuntimeError):
                accept.locked_baseline(data)

    def test_pinned_artifacts_both_valid(self):
        for slot in "AB":
            path, image = accept.pinned_image(slot)
            self.assertTrue(path.is_file())
            self.assertEqual(accept.image_info(image)[0], slot)

    def test_no_sample_unlock_or_forced_confirmation_in_host(self):
        source = Path(accept.__file__).read_text(encoding="utf-8")
        for command in ('"ZERO SAMPLE"', '"START"', '"CLEAR"', '"FW CONFIRM"',
                        '"BOOT A"', '"BOOT B"', '"FW ABORT"'):
            self.assertNotIn(command, source)
        self.assertLess(source.index('result["staged_flash"]'), source.index('uart.command("FW END"'))
        self.assertIn("allow_reset=False", source)

    def test_console_wait_only_retries_read_only_query(self):
        class FakeUart:
            def __init__(self):
                self.calls = []
            def query(self, command, timeout):
                self.calls.append(command)
                if len(self.calls) == 1:
                    raise TimeoutError("RX not initialized")
                return "OK CURRENT=B CONFIRMED=B PENDING=- ATTEMPTS=0 ACTIVE=0"
        uart = FakeUart()
        self.assertEqual(accept.await_confirmed_console(uart, "B")["CURRENT"], "B")
        self.assertEqual(uart.calls, ["FW STATUS", "FW STATUS"])


if __name__ == "__main__":
    unittest.main()
