"""Resume this interrupted acceptance only, after independent Flash-prefix verification."""
import argparse
import re
import time
import zlib
from pathlib import Path
import serial

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--permit-flash-reset", action="store_true", required=True)
args = parser.parse_args()
root = Path(__file__).resolve().parents[1]
evidence = root / "safety_backups/20261005-router-live-acceptance"
image = (root / "foc2_app_a/build/RouterNetworkReadOnly/foc2.bin").read_bytes()
dump = (evidence / "stm32-interrupted.bin").read_bytes()
crc = zlib.crc32(image)
port = serial.Serial(port=None, baudrate=115200, timeout=.1, write_timeout=2)
port.dtr = port.rts = False
port.port = "COM5"
request = 32000
log = (evidence / "iap-resume.log").open("a", encoding="utf-8")


def record(line):
    log.write(line + "\n")
    log.flush()
    print(line, flush=True)


def command(text, timeout=5):
    global request
    if not re.fullmatch(r"FW (STATUS|END|DATA [0-9A-F]{8} [0-9A-F]+)", text):
        raise ValueError("Out-of-scope command")
    request += 1
    port.write((str(request) + " " + text + "\r\n").encode())
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        line = port.readline().decode(errors="replace").strip()
        if line.startswith(str(request) + " "):
            record(line)
            if not line.startswith(str(request) + " OK "):
                raise RuntimeError(line)
            return line
    raise TimeoutError(text.split()[1])


try:
    port.open()
    port.reset_input_buffer()
    status = command("FW STATUS")
    expected = "CURRENT=B TARGET=A ACTIVE=1"
    if expected not in status or "CONFIRMED=B PENDING=- ATTEMPTS=0" not in status:
        raise RuntimeError("No matching interrupted upgrade; nothing written")
    received = int(re.search(r"\bRX=(\d+)", status)[1])
    size = int(re.search(r"\bSIZE=(\d+)", status)[1])
    expected_crc = int(re.search(r"EXPECT=0x([0-9A-Fa-f]+)", status)[1], 16)
    if size != len(image) or expected_crc != crc or received != 185824:
        raise RuntimeError("Interrupted transaction does not match this exact image")
    if len(dump) != 524288 or dump[0x8000:0x8000 + received] != image[:received]:
        raise RuntimeError("Independent Flash prefix check failed; no resume")
    record("PASS independent Flash prefix: " + str(received) + " bytes match image")
    while received < len(image):
        part = image[received:received + 32]
        command("FW DATA %08X %s" % (received, part.hex().upper()))
        received += len(part)
    status = command("FW STATUS")
    if "RX=" + str(len(image)) + " " not in status:
        raise RuntimeError("Complete byte count not confirmed")
    command("FW END", timeout=20)
    record("RESUME PASS: complete CRC checked by board; trial reset requested")
finally:
    port.close()
    log.close()
