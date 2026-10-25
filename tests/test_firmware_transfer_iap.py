"""No COM port, no Flash, no subprocess: exercise the local upgrade safety contract."""

from app_source_view import read_app_source
import importlib.util
import struct
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("fw_iap", ROOT / "tools/firmware_transfer_iap.py")
iap = importlib.util.module_from_spec(spec)
spec.loader.exec_module(iap)
IMAGE = struct.pack("<II", 0x2001FFF8, 0x08040009) + bytes(range(64))
SAFE = "1 OK SAFE LATCHED=1 SD=0 MOE=0 FOC=0"
FW = "1 OK FW CURRENT=A CONFIRMED=A TARGET=B ACTIVE=0 PENDING=-"
ENGINE = "1 OK FWTRANSFER ENGINE=OFFICIAL READY=1 BUSY=0 CH=3 RESOURCE=2 MTU=96"


class ImagePath:
    def read_bytes(self):
        return IMAGE


class FakeNative:
    closed = False
    def __init__(self, *args):
        pass
    def close(self):
        self.closed = True


class FakeUart:
    def __init__(self, safe=SAFE, complete=True):
        self.commands = []
        self.safe = safe
        self.complete = complete
        self.on_rpc = lambda text: None
    def command(self, text, timeout=5):
        self.commands.append(text)
        if text == "FW STATUS":
            if not any(x.startswith("FW BEGIN ") for x in self.commands):
                return FW
            return (f"1 OK FW CURRENT=A CONFIRMED=A TARGET=B ACTIVE=1 PENDING=- "
                    f"RX={len(IMAGE)} SIZE={len(IMAGE)} EXPECT=0x{iap.image_info(IMAGE)[1]:08X}")
        if text == "ANALOG SAFE STATUS":
            return self.safe
        if text == "XFER ENGINE STATUS":
            if "XFER ENGINE CLOSE" in self.commands:
                return ENGINE + " PHASE=0"
            if any(x.startswith("FW BEGIN ") for x in self.commands):
                return ENGINE.replace("BUSY=0", "BUSY=1") + (
                    f" PHASE=3 RESULT=0 RX={len(IMAGE)}" if self.complete else " PHASE=4 RESULT=15 RX=0")
            return ENGINE
        return "1 OK ACCEPTED"


class FakeSerial:
    def __init__(self, parts):
        self.parts = list(parts)
        self.writes = []
    @property
    def in_waiting(self):
        return 1
    def read(self, n):
        return self.parts.pop(0) if self.parts else b""
    def write(self, wire):
        self.writes.append(wire)


class SafetyTests(unittest.TestCase):
    def test_vectors_and_capacity(self):
        self.assertEqual(iap.image_info(IMAGE)[0], "B")
        for bad in (b"x", IMAGE + bytes(iap.CAPACITY),
                    struct.pack("<II", 0x2001FFF8, 0x08040008) + IMAGE[8:],
                    struct.pack("<II", 0x2001FFF9, 0x08040009) + IMAGE[8:],
                    struct.pack("<II", 0x2001FFF8, 0x08040101) + IMAGE[8:]):
            with self.assertRaises(ValueError):
                iap.image_info(bad)

    def test_slot_trial_busy_and_safety(self):
        iap.preflight(FW, SAFE, ENGINE, "B")
        for status, safe, engine in (
                (FW.replace("TARGET=B", "TARGET=A"), SAFE, ENGINE),
                (FW.replace("CONFIRMED=A", "CONFIRMED=B"), SAFE, ENGINE),
                (FW.replace("PENDING=-", "PENDING=B"), SAFE, ENGINE),
                (FW.replace("ACTIVE=0", "ACTIVE=1"), SAFE, ENGINE),
                (FW, SAFE.replace("MOE=0", "MOE=1"), ENGINE),
                (FW, SAFE.replace("SD=0", "SD=1"), ENGINE),
                (FW, SAFE.replace("LATCHED=1", "LATCHED=0"), ENGINE),
                (FW, SAFE, ENGINE.replace("BUSY=0", "BUSY=1")),
                (FW, SAFE, ENGINE.replace("READY=1", "READY=0"))):
            with self.assertRaises(RuntimeError):
                iap.preflight(status, safe, engine, "B")

    def test_default_stage_does_not_reset(self):
        uart = FakeUart()
        with patch.object(iap, "transfer"):
            iap.stage(uart, ImagePath(), Path("unused"), native_factory=FakeNative)
        self.assertNotIn("FW END", uart.commands)
        self.assertNotIn("FW ABORT", uart.commands)
        self.assertIn("XFER ENGINE CLOSE", uart.commands)

    def test_explicit_reset_only_after_complete_and_close(self):
        uart = FakeUart()
        with patch.object(iap, "transfer"):
            iap.stage(uart, ImagePath(), Path("unused"), True, FakeNative)
        self.assertLess(uart.commands.index("XFER ENGINE CLOSE"), uart.commands.index("FW END"))

    def test_unsafe_state_never_erases(self):
        uart = FakeUart(safe=SAFE.replace("FOC=0", "FOC=1"))
        with self.assertRaises(RuntimeError):
            iap.stage(uart, ImagePath(), Path("unused"), True, FakeNative)
        self.assertFalse(any(x.startswith("FW BEGIN") for x in uart.commands))

    def test_failure_never_commits_or_resets(self):
        for fail in (False, True):
            uart = FakeUart(complete=fail)
            with patch.object(iap, "transfer", side_effect=RuntimeError("lost UART") if fail else None):
                with self.assertRaises(RuntimeError):
                    iap.stage(uart, ImagePath(), Path("unused"), True, FakeNative)
            self.assertIn("XFER ENGINE CLOSE", uart.commands)
            self.assertNotIn("FW END", uart.commands)
            self.assertNotIn("FW ABORT", uart.commands)

    def test_partial_lines_and_rpc_while_waiting_for_ack(self):
        serial = FakeSerial([b"0 EVT FWTRA", b"NSFER RPC AABB\r\n150", b"01 OK ACCEPTED\r\n"])
        uart = iap.Uart(serial)
        events = []
        uart.on_rpc = events.append
        self.assertEqual(uart.command("XFER ENGINE AABB"), "15001 OK ACCEPTED")
        self.assertEqual(events, ["AABB"])
        self.assertEqual(serial.writes, [b"15001 XFER ENGINE AABB\r\n"])
        with self.assertRaises(ValueError):
            uart.command("START")
        with self.assertRaises(ValueError):
            uart.command("FW ABORT")

    def test_board_port_limits_and_busy_owner_gate(self):
        port = (ROOT / "firmware_common/uart_firmware_transfer_port.inc").read_text()
        for guard in ("fw_update.active", "APP_TARGET_ADDRESS", "foc_enable", "TIM_BDTR_MOE",
                      "GPIO_PIN_RESET", "Fw_TargetVectorValid", "Fw_TargetCrc32", "LOCAL_UART_ONLY"):
            self.assertIn(guard, port)
        for slot in ("a", "b"):
            main = read_app_source(ROOT / f"foc2_app_{slot}/Core/Src/main.c")
            self.assertIn("OFFICIAL_TRANSFER_OWNS_IAP", main)
            self.assertIn("PW_UartFirmwareTransfer_Service();", main)
            self.assertIn("packet.src == 0U", main)


if __name__ == "__main__":
    unittest.main()
