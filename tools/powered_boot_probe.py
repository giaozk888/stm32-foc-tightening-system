"""Observe one previously staged normal APP trial; never send motion commands.

Default is read-only. --commit-staged permits only FW END after exact image,
inactive-slot, confirmed-slot and power-off checks. No forced confirmation,
fault clearing, automatic flash retry or automatic reset recovery.
"""

import argparse
import re
import subprocess
import time
from pathlib import Path

from firmware_transfer_iap import Uart, fields, image_info


class ProbeUart(Uart):
    def dispatch(self, line):
        if line:
            print("RX " + line, flush=True)
        if any(message in line for message in (
                "STATIC CURRENT ZERO CAL FAILED", "PWM-ON RUN ZERO CAL ERROR",
                "ADC1 hardware calibration FAILED", "ADC2 hardware calibration FAILED",
                "AS5047P STARTUP CHECK FAILED", "ENCODER READ FAILED BEFORE FOC ENABLE",
                "CREATE FAILED", "HardFault", "TWO ADC RUN ZERO CAL INVALID",
                "TWO ADC RUN ZERO CAL TIMEOUT")):
            raise RuntimeError("Startup protection refused this trial: " + line)

    def query(self, text, timeout=1.0):
        if text not in ("FW STATUS", "ANALOG SAFE STATUS", "SELFTEST STATUS", "STATUS"):
            raise ValueError("Probe query is read-only")
        self.request += 1
        request = self.request
        self.port.write(f"{request} {text}\r\n".encode("ascii"))
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            line = self.read_line(min(0.05, deadline - time.monotonic()))
            if line is None:
                continue
            self.dispatch(line)
            if line.startswith(f"{request} "):
                if not line.startswith(f"{request} OK "):
                    raise RuntimeError(line)
                return line
        raise TimeoutError("No reply: " + text)


def require_staged(fw_line, safe_line, image):
    slot, crc = image_info(image)
    fw, safe = fields(fw_line), fields(safe_line)
    if (fw.get("CURRENT") not in ("A", "B") or
            fw.get("CURRENT") != fw.get("CONFIRMED") or
            fw.get("TARGET") != slot or fw.get("CURRENT") == slot or
            fw.get("PENDING") != "-" or fw.get("ATTEMPTS") != "0" or
            fw.get("ACTIVE") != "1" or fw.get("RX") != str(len(image)) or
            fw.get("SIZE") != str(len(image)) or
            fw.get("EXPECT", "").upper() != f"0X{crc:08X}"):
        raise RuntimeError("Exact inactive image is not completely staged")
    off_keys = (("SD", "0"), ("MOE", "0"), ("CEN", "0")) if safe.get("SOURCE") == "SWD" else (
        ("LATCHED", "1"), ("SD", "0"), ("MOE", "0"), ("FOC", "0"))
    if any(safe.get(key) != value for key, value in off_keys):
        raise RuntimeError("Power stage is not locked off")
    return slot


def register_safe_line(output):
    registers = dict((int(address, 16), int(value, 16)) for address, value in
                     re.findall(r"(?im)^0x([0-9a-f]+)\s*:\s*([0-9a-f]{8})\s*$", output))
    if any(address not in registers for address in (0x48000814, 0x40012C44, 0x40012C00)):
        raise RuntimeError("Incomplete SWD power-off proof")
    if (registers[0x48000814] & (1 << 6) or registers[0x40012C44] & (1 << 15) or
            registers[0x40012C00] & 1):
        raise RuntimeError("SWD confirms an active gate/PWM/timer; trial is forbidden")
    # This proves physical outputs off, not the state of software latch/FOC.
    return "0 OK SAFE SOURCE=SWD SD=0 MOE=0 CEN=0"


def read_staged_hardware_safe():
    completed = subprocess.run([
        r"D:\software\cubeprogrammer\bin\STM32_Programmer_CLI.exe",
        "-c", "port=SWD", "mode=HOTPLUG", "freq=1000", "sn=0050003B3235511537333439",
        "-r32", "0x48000814", "4", "-r32", "0x40012C44", "4", "-r32", "0x40012C00", "4"],
        capture_output=True, text=True, errors="replace", timeout=15)
    if completed.returncode != 0:
        raise RuntimeError("Read-only SWD power-off verification failed")
    safe = register_safe_line(completed.stdout)
    print(safe, flush=True)
    return safe


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", default="COM5")
    parser.add_argument("--image", type=Path, required=True)
    parser.add_argument("--commit-staged", action="store_true")
    args = parser.parse_args()
    image = args.image.read_bytes()
    slot, _ = image_info(image)
    import serial
    port = serial.Serial(port=None, baudrate=115200, timeout=0.02, write_timeout=0.5)
    port.dtr = port.rts = False
    port.port = args.port
    try:
        port.open()
        uart = ProbeUart(port)
        uart.request = 53000
        fw = uart.query("FW STATUS", 3)
        try:
            safe = uart.query("ANALOG SAFE STATUS", 3)
        except RuntimeError as error:
            if "FW_UPDATE_ACTIVE" not in str(error) or fields(fw).get("ACTIVE") != "1":
                raise
            # Older deployed APP permits only FW commands while staging.
            # Do not bypass the power-off check; read actual gate/timer bits.
            safe = read_staged_hardware_safe()
        if not args.commit_staged:
            print("READ-ONLY: no FW END, reset or motion command sent", flush=True)
            return
        require_staged(fw, safe, image)
        # FW END rechecks full Flash CRC/vector in firmware, then resets into
        # a trial. A lost END ACK is not retried; observe the existing trial.
        try:
            uart.command("FW END", timeout=3)
        except TimeoutError:
            print("FW END ACK uncertain; observing, not retrying", flush=True)
        deadline = time.monotonic() + 45
        while time.monotonic() < deadline:
            try:
                fw = fields(uart.query("FW STATUS"))
            except TimeoutError:
                continue
            if (fw.get("CURRENT") == slot and fw.get("CONFIRMED") == slot and
                    fw.get("PENDING") == "-" and fw.get("ATTEMPTS") == "0" and
                    fw.get("ACTIVE") == "0"):
                health = fields(uart.query("SELFTEST STATUS"))
                status = fields(uart.query("STATUS"))
                safe = fields(uart.query("ANALOG SAFE STATUS"))
                if (health.get("READY") != "1" or health.get("MASK") != "0x000" or
                        status.get("MODE") != "IDLE" or status.get("BUSY") != "0" or
                        status.get("FLT") != "0" or safe.get("LATCHED") != "0"):
                    raise RuntimeError("Confirmed image failed normal-control preflight")
                print(f"BOOT PROBE PASS: confirmed {slot}, real calibration/selftest ready; NO START SENT", flush=True)
                return
            if fw.get("CURRENT") != slot and fw.get("PENDING") == "-":
                raise RuntimeError("Bootloader returned to the previous confirmed image")
            time.sleep(0.1)
        raise TimeoutError("Trial did not become confirmed/ready; no motion permitted")
    finally:
        port.close()


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, RuntimeError, TimeoutError) as error:
        raise SystemExit("BOOT PROBE FAILED: " + str(error))
