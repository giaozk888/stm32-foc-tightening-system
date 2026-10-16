"""Two real official engines + Python UART orchestration; RAM Flash only, no COM ports."""
import importlib.util
import queue
import struct
import subprocess
import sys
import threading
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("fw_iap", ROOT / "tools/firmware_transfer_iap.py")
iap = importlib.util.module_from_spec(spec)
spec.loader.exec_module(iap)


class PipeSerial:
    def __init__(self, server):
        self.server = server
        self.lines = queue.Queue()
        self.buffer = bytearray()
        self.reader = threading.Thread(target=self._read, daemon=True)
        self.reader.start()

    def _read(self):
        for line in self.server.stdout:
            self.lines.put(line)

    @property
    def in_waiting(self):
        return len(self.buffer)

    def read(self, n):
        if not self.buffer:
            try:
                self.buffer.extend(self.lines.get(timeout=0.005))
            except queue.Empty:
                return b""
        result = bytes(self.buffer[:n])
        del self.buffer[:n]
        return result

    def write(self, wire):
        self.server.stdin.write(wire)
        self.server.stdin.flush()


def main():
    server_exe, client_exe, directory = map(Path, sys.argv[1:])
    image = struct.pack("<II", 0x2001FFF8, 0x08040009) + bytes(i*37 % 256 for i in range(2049))
    image_path = directory / "stdio_test_image.bin"
    image_path.write_bytes(image)  # Generated test artifact under the CMake build directory.
    server = subprocess.Popen([str(server_exe), str(image_path), f"{zlib.crc32(image):08X}"],
                              stdin=subprocess.PIPE, stdout=subprocess.PIPE)
    serial = PipeSerial(server)
    try:
        iap.stage(iap.Uart(serial), image_path, client_exe)
        print("PASS real stdio client/server + UART event/ACK demultiplex + no reset")
    finally:
        server.stdin.close()
        try:
            server.wait(timeout=5)
        except subprocess.TimeoutExpired:
            server.kill()
            server.wait(timeout=3)
        serial.reader.join(timeout=3)
        server.stdout.close()


if __name__ == "__main__":
    main()
