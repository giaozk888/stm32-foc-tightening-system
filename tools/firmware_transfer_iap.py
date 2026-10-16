"""Local UART IAP using the pinned official C++ pw_transfer client.

No hardware access without --allow-upgrade; staging is the default.
--allow-reset additionally permits FW END and the existing A/B trial reset.
"""
import argparse
import queue
import re
import struct
import subprocess
import threading
import time
import zlib
from pathlib import Path

CAPACITY = 224 * 1024
ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CLIENT = ROOT / "tests/uart_firmware_transfer_host/build/firmware_transfer_client.exe"
EVENT = re.compile(r"0 EVT FWTRANSFER RPC ([0-9A-F]{2,192})$")


def fields(line):
    return dict(re.findall(r"\b([A-Z][A-Z0-9_]*)=([^\s]+)", line))


def image_info(image):
    if not 8 <= len(image) <= CAPACITY:
        raise ValueError("Image must be 8..229376 bytes")
    sp, reset = struct.unpack_from("<II", image)
    if not 0x20000000 < sp <= 0x20020000 or sp % 8 or not reset & 1:
        raise ValueError("Invalid initial stack pointer or Thumb reset vector")
    pc = reset & ~1
    for slot, base in (("A", 0x08008000), ("B", 0x08040000)):
        if base <= pc < base + len(image):
            return slot, zlib.crc32(image)
    raise ValueError("Reset vector must be inside this image's APP A/B slot")


def preflight(status, safe, engine, slot):
    fw, safety, xfer = fields(status), fields(safe), fields(engine)
    if (fw.get("CURRENT") not in ("A", "B") or
            fw.get("CURRENT") != fw.get("CONFIRMED") or
            fw.get("TARGET") != slot or fw.get("CURRENT") == slot or
            fw.get("ACTIVE") != "0" or fw.get("PENDING") != "-"):
        raise RuntimeError("Need confirmed, idle APP; image must target its inactive slot")
    if any(safety.get(k) != v for k, v in
           (("LATCHED", "1"), ("SD", "0"), ("MOE", "0"), ("FOC", "0"))):
        raise RuntimeError("Power stage is not latched safe; no Flash operation allowed")
    if any(xfer.get(k) != v for k, v in
           (("ENGINE", "OFFICIAL"), ("READY", "1"), ("BUSY", "0"),
            ("CH", "3"), ("RESOURCE", "2"), ("MTU", "96"))):
        raise RuntimeError("Official UART transfer engine is unavailable or already busy")


class Uart:
    """One reader owns UART. Keep partial lines and demultiplex unsolicited RPC."""
    def __init__(self, serial_port, verbose=False):
        self.port = serial_port
        self.verbose = verbose
        self.request = 15000
        self.buffer = bytearray()
        self.on_rpc = lambda text: None

    def read_line(self, timeout):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if b"\n" in self.buffer:
                line, _, rest = self.buffer.partition(b"\n")
                self.buffer = bytearray(rest)
                return line.decode("ascii", errors="replace").strip()
            self.buffer.extend(self.port.read(min(max(self.port.in_waiting, 1), 1024)))
            if len(self.buffer) > 8192:
                raise RuntimeError("Unterminated UART line exceeds bounded parser")
        return None

    def dispatch(self, line):
        event = EVENT.fullmatch(line)
        if event:
            if len(event[1]) % 2:
                raise RuntimeError("Odd-length transfer RPC event")
            self.on_rpc(event[1])
        elif self.verbose:
            print("RX " + line, flush=True)

    def poll(self, timeout=0.02):
        line = self.read_line(timeout)
        if line is not None:
            self.dispatch(line)

    def command(self, text, timeout=5):
        # This orchestrator never sends a motion, network or bootloader command.
        if not re.fullmatch(
                r"FW (STATUS|END|BEGIN [0-9]+ [0-9A-F]{8})|ANALOG SAFE STATUS|"
                r"XFER ENGINE (STATUS|CLOSE|[0-9A-F]{2,192})", text):
            raise ValueError("Out-of-scope UART command")
        self.request += 1
        wire = f"{self.request} {text}\r\n".encode("ascii")
        if len(wire) >= 224:
            raise ValueError("Command exceeds firmware UART line capacity")
        self.port.write(wire)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            line = self.read_line(min(0.1, deadline-time.monotonic()))
            if line is None:
                continue
            self.dispatch(line)
            if line.startswith(f"{self.request} "):
                if not line.startswith(f"{self.request} OK "):
                    raise RuntimeError(line)
                return line
        # Do not retry a destructive command whose outcome is unknown.
        raise TimeoutError("No ACK for " + text.split()[0] + " command")


def close_engine(uart):
    uart.command("XFER ENGINE CLOSE")
    deadline = time.monotonic() + 8
    while time.monotonic() < deadline:
        status = uart.command("XFER ENGINE STATUS")
        if fields(status).get("BUSY") == "0":
            return
        time.sleep(0.02)
    raise TimeoutError("Transfer worker did not close; FW END must not be sent")


class NativeClient:
    def __init__(self, executable, image):
        self.lines = queue.Queue(maxsize=32)
        self.process = subprocess.Popen(
            [str(executable), str(image)], stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            text=True, bufsize=1)
        self.reader = threading.Thread(target=self._read, daemon=True)
        self.reader.start()

    def _read(self):
        try:
            for line in self.process.stdout:
                self.lines.put(line.strip(), timeout=3)
        except queue.Full:
            pass
        finally:
            try:
                self.lines.put(None, timeout=3)
            except queue.Full:
                pass

    def send(self, line):
        if self.process.poll() is not None:
            return  # A queued terminal RESULT is consumed by the UART loop.
        try:
            self.process.stdin.write(line + "\n")
            self.process.stdin.flush()
        except BrokenPipeError:
            pass  # EOF without a terminal RESULT still fails closed.

    def close(self):
        if self.process.poll() is None:
            self.process.terminate()
        try:
            self.process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait(timeout=3)
        self.reader.join(timeout=4)
        self.process.stdin.close()
        self.process.stdout.close()


def transfer(uart, native, timeout=900):
    uart.on_rpc = lambda text: native.send("RPC " + text)
    deadline = time.monotonic() + timeout
    next_tick = 0
    while time.monotonic() < deadline:
        try:
            line = native.lines.get_nowait()
        except queue.Empty:
            line = ""
        if line is None:
            raise RuntimeError("Official client ended without a result")
        if line.startswith("RPC "):
            uart.command("XFER ENGINE " + line[4:])
        elif line == "RESULT OK 0":
            uart.on_rpc = lambda text: None
            return
        elif line.startswith("RESULT "):
            raise RuntimeError(line)
        elif line:
            raise RuntimeError("Unexpected official client output")
        if time.monotonic() >= next_tick:
            native.send("TICK")
            next_tick = time.monotonic() + 0.03
        uart.poll()
    raise TimeoutError("Official transfer exceeded bounded wall-clock limit")


def stage(uart, image_path, client_path, allow_reset=False, native_factory=NativeClient):
    image = image_path.read_bytes()
    slot, crc = image_info(image)
    status = uart.command("FW STATUS")
    safe = uart.command("ANALOG SAFE STATUS")
    engine = uart.command("XFER ENGINE STATUS")
    preflight(status, safe, engine, slot)
    print(f"Preflight PASS: inactive {slot}, size={len(image)}, CRC32={crc:08X}")
    native = None
    began = False
    try:
        uart.command(f"FW BEGIN {len(image)} {crc:08X}", timeout=60)
        began = True
        native = native_factory(client_path, image_path)
        transfer(uart, native)
        completed = fields(uart.command("XFER ENGINE STATUS"))
        if (completed.get("PHASE") != "3" or completed.get("RESULT") != "0" or
                completed.get("RX") != str(len(image))):
            raise RuntimeError("Device did not confirm successful full-image verification")
        close_engine(uart)
        uart.on_rpc = lambda text: None
        staged = fields(uart.command("FW STATUS"))
        if (staged.get("ACTIVE") != "1" or staged.get("TARGET") != slot or
                staged.get("RX") != str(len(image)) or staged.get("SIZE") != str(len(image)) or
                staged.get("EXPECT", "").upper() != f"0X{crc:08X}"):
            raise RuntimeError("Staged firmware transaction does not match the image")
        if allow_reset:
            uart.command("FW END", timeout=20)
            print("TRANSFER PASS: FW END accepted; A/B trial reset requested (not yet confirmed)")
        else:
            print("STAGE PASS: inactive image verified; no FW END, reset or trial requested")
    except BaseException:
        uart.on_rpc = lambda text: None
        if began:
            try:
                close_engine(uart)
            except Exception as error:
                print("Cleanup warning: " + str(error))
            print("Upgrade left uncommitted. No automatic FW ABORT/reset; inspect FW STATUS.")
        raise
    finally:
        uart.on_rpc = lambda text: None
        if native:
            native.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", required=True)
    parser.add_argument("--image", required=True, type=Path)
    parser.add_argument("--client", type=Path, default=DEFAULT_CLIENT)
    parser.add_argument("--baud", type=int, default=115200)
    parser.add_argument("--allow-upgrade", action="store_true",
                        help="permit inactive-slot erase/program; mechanically isolate first")
    parser.add_argument("--allow-reset", action="store_true", help="also permit FW END / trial reset")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()
    if not args.allow_upgrade:
        parser.error("--allow-upgrade is required before opening UART or erasing/programming")
    image_info(args.image.read_bytes())
    if not args.client.is_file():
        parser.error("Build tests/uart_firmware_transfer_host first; native official client is missing")
    import serial  # --help and pure offline tests do not require pyserial.
    port = serial.Serial(port=None, baudrate=args.baud, timeout=0.02, write_timeout=2)
    port.dtr = port.rts = False
    port.port = args.port
    try:
        port.open()
        stage(Uart(port, args.verbose), args.image.resolve(), args.client.resolve(), args.allow_reset)
    finally:
        port.close()


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, RuntimeError, TimeoutError) as error:
        raise SystemExit("FAILED: " + str(error))
