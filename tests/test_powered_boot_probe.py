"""Offline safety checks: no COM port, Flash or motor operations."""

import struct
import sys
import unittest
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from powered_boot_probe import ProbeUart, require_staged, register_safe_line


class PoweredBootProbeTest(unittest.TestCase):
    image = struct.pack("<II", 0x2001FFF8, 0x08040009) + bytes(range(64))
    safe = "1 OK SAFE LATCHED=1 SD=0 MOE=0 FOC=0"

    def fw(self):
        return (f"1 OK FW CURRENT=A CONFIRMED=A TARGET=B ACTIVE=1 "
                f"PENDING=- ATTEMPTS=0 RX={len(self.image)} SIZE={len(self.image)} "
                f"EXPECT=0x{zlib.crc32(self.image):08X}")

    def test_exact_staged_inactive(self):
        self.assertEqual(require_staged(self.fw(), self.safe, self.image), "B")

    def test_reject_active_slot(self):
        with self.assertRaises(RuntimeError):
            require_staged(self.fw().replace("CURRENT=A", "CURRENT=B"), self.safe, self.image)

    def test_reject_partial_or_wrong_crc_or_pending(self):
        for field, bad in ((f"RX={len(self.image)}", "RX=0"),
                           (f"EXPECT=0x{zlib.crc32(self.image):08X}", "EXPECT=0x00000000"),
                           ("PENDING=-", "PENDING=B"), ("ACTIVE=1", "ACTIVE=0")):
            with self.subTest(field=field), self.assertRaises(RuntimeError):
                require_staged(self.fw().replace(field, bad), self.safe, self.image)

    def test_reject_unlocked_outputs(self):
        for key in ("SD", "MOE", "FOC"):
            with self.subTest(key=key), self.assertRaises(RuntimeError):
                require_staged(self.fw(), self.safe.replace(key + "=0", key + "=1"), self.image)

    def test_startup_fault_stops_probe(self):
        for line in ("STATIC CURRENT ZERO CAL FAILED", "PWM-ON RUN ZERO CAL ERROR",
                     "AS5047P STARTUP CHECK FAILED", "RouterTask CREATE FAILED"):
            with self.subTest(line=line), self.assertRaises(RuntimeError):
                ProbeUart(None).dispatch(line)

    def test_motion_query_forbidden_before_port_write(self):
        with self.assertRaises(ValueError):
            ProbeUart(None).query("START")

    def test_real_register_off_proof(self):
        output = "0x48000814 : 00000000\n0x40012C44 : 02002055\n0x40012C00 : 00000020\n"
        self.assertEqual(require_staged(self.fw(), register_safe_line(output), self.image), "B")
        for old, bad in (("00000000", "00000040"), ("02002055", "0200A055"),
                         ("00000020", "00000021")):
            with self.subTest(bad=bad), self.assertRaises(RuntimeError):
                register_safe_line(output.replace(old, bad))
        with self.assertRaises(RuntimeError):
            register_safe_line("")


if __name__ == "__main__":
    unittest.main()
