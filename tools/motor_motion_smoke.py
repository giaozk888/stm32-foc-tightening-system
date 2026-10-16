"""Bounded, no-load UART motion check for the STM32G474.

Default mode is read-only. --execute requires an already isolated mechanical
load and sends one short START/STOP at a target in the normal recipe range,
then latches ANALOG SAFE. This is not a loaded tightening qualification.
"""

import argparse
import re
import time

import serial
from firmware_transfer_iap import fields


BOUNDS = {
    # Match the default in firmware_common/tighten_params.h. This is a target,
    # not a measured speed or a validated industrial process requirement.
    "RUNDOWN_RPM": 80,
    "RUNDOWN_TIMEOUT_MS": 1000,
    "MAX_TRAVEL_DEG": 100,
    "CONTACT_RPM": 1,
    "CONTACT_IQ_MA": 400,
    "CONTACT_MS": 1000,
}

# Keep the original short-test stop deadline; changing the target must not
# silently extend motion or weaken the independent on-board timeout/travel cap.
HOST_STOP_SECONDS = 0.4
TARGET_RPM_RANGE = (20, 120)


def bounded_recipe(target_rpm):
    """Override only the target; do not widen any protection or time bound."""
    if not TARGET_RPM_RANGE[0] <= target_rpm <= TARGET_RPM_RANGE[1]:
        raise ValueError("Target must remain in the normal 20..120 rpm recipe range")
    return {**BOUNDS, "RUNDOWN_RPM": target_rpm}


class Board:
    def __init__(self, port):
        self.serial = serial.Serial(port=None, baudrate=115200, timeout=0.01, write_timeout=0.2)
        self.serial.dtr = self.serial.rts = False
        self.serial.port = port
        self.serial.open()
        self.buffer = bytearray()
        self.next_id = 7800
        time.sleep(0.2)
        self.serial.reset_input_buffer()

    def close(self):
        self.serial.close()

    def send(self, command):
        request_id = self.next_id
        self.next_id += 1
        self.serial.write(f"{request_id} {command}\r\n".encode("ascii"))
        return request_id

    def read_line(self, seconds=0.02):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            if b"\n" in self.buffer:
                line, _, remainder = self.buffer.partition(b"\n")
                self.buffer = bytearray(remainder)
                return line.decode("ascii", "replace").strip()
            self.buffer.extend(self.serial.read(min(max(self.serial.in_waiting, 1), 1024)))
            if len(self.buffer) > 8192:
                raise RuntimeError("UART line exceeded bounded parser")
        return None

    def reply(self, request_id, seconds=2.0):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            line = self.read_line(min(0.02, deadline - time.monotonic()))
            if line is None:
                continue
            if line.startswith(f"{request_id} "):
                print(line, flush=True)
                if not line.startswith(f"{request_id} OK "):
                    raise RuntimeError(line)
                return line
        raise TimeoutError(f"No reply for request {request_id}")

    def command(self, command, seconds=2.0):
        return self.reply(self.send(command), seconds)


def require_idle_ready(board, expected_slot="A"):
    fw = board.command("FW STATUS")
    health = board.command("SELFTEST STATUS")
    status = board.command("STATUS")
    safe = board.command("ANALOG SAFE STATUS")
    f, h, s, a = map(fields, (fw, health, status, safe))
    if (f.get("CURRENT") != expected_slot or f.get("CONFIRMED") != expected_slot
            or f.get("PENDING") != "-" or f.get("ACTIVE") != "0"
            or f.get("ATTEMPTS") != "0" or h.get("READY") != "1" or h.get("MASK") != "0x000"
            or s.get("MODE") != "IDLE" or s.get("BUSY") != "0"
            or s.get("FLT") != "0" or a.get("LATCHED") != "0"):
        raise RuntimeError("Preflight not ready/idle/confirmed or already safe")
    return status


def position(status):
    match = re.search(r"\bPOS=([-+]?\d+(?:\.\d+)?)deg\b", status)
    return float(match.group(1)) if match else None


def wait_for_idle(board, seconds=3.0):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        status = board.command("STATUS", 1.0)
        match = re.search(r"\bCTRL=([-+]?\d+(?:\.\d+)?)rpm\b", status)
        slow = match is not None and abs(float(match.group(1))) < 2.0
        if "MODE=IDLE" in status and "BUSY=0" in status and slow:
            return status
        time.sleep(0.1)
    raise TimeoutError("Motor did not return to IDLE")


def stop(board):
    last_error = None
    for _ in range(3):
        try:
            return board.command("STOP", 0.8)
        except (OSError, TimeoutError, RuntimeError) as exc:
            last_error = exc
    raise RuntimeError(f"STOP was not acknowledged: {last_error}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", default="COM5")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--expected-slot", choices=("A", "B"), default="A")
    parser.add_argument("--target-rpm", type=int, default=BOUNDS["RUNDOWN_RPM"])
    args = parser.parse_args()
    # Reject invalid requests before even opening the serial port.
    try:
        bounds = bounded_recipe(args.target_rpm)
    except ValueError as error:
        parser.error(str(error))

    board = Board(args.port)
    original = {}
    changed = []
    samples = []
    started = False
    try:
        baseline = require_idle_ready(board, args.expected_slot)
        print(f"Baseline position: {position(baseline)} deg", flush=True)
        if not args.execute:
            print("READ-ONLY PASS; no motor command sent", flush=True)
            return

        print(f"Target={args.target_rpm}rpm; host STOP={HOST_STOP_SECONDS}s; "
              "not a steady-speed or torque qualification", flush=True)

        for name in bounds:
            line = board.command(f"GET {name}")
            match = re.search(rf"\b{name}=(\d+)\b", line)
            if not match:
                raise RuntimeError(f"Cannot read original {name}")
            original[name] = int(match.group(1))
        for name, value in bounds.items():
            # Mark before sending: a missing ACK may still mean SET was applied.
            changed.append(name)
            board.command(f"SET {name} {value}")
            line = board.command(f"GET {name}")
            if fields(line).get(name) != str(value):
                raise RuntimeError(f"Temporary limit not verified: {name}")

        # Give the parallel CAN recorder time to enter candump before motion.
        time.sleep(1.5)
        require_idle_ready(board, args.expected_slot)
        # A write timeout does not prove START was unreceived. Arm cleanup
        # before attempting the write; finally must STOP even on an uncertain ACK.
        started = True
        start_id = board.send("START")
        start_at = time.monotonic()
        deadline = start_at + HOST_STOP_SECONDS
        samples_at = [start_at + t for t in (0.05, 0.10, 0.20, 0.30, 0.35)]
        sample_ids = set()
        start_reply = None
        while time.monotonic() < deadline:
            if samples_at and time.monotonic() >= samples_at[0]:
                sample_ids.add(board.send("STATUS"))
                samples_at.pop(0)
            line = board.read_line(min(0.01, max(0, deadline - time.monotonic())))
            if line is None:
                continue
            if line.startswith(f"{start_id} "):
                start_reply = line
                print(line, flush=True)
                if not line.startswith(f"{start_id} OK "):
                    raise RuntimeError("START was refused: " + line)
            elif any(line.startswith(f"{request_id} ") for request_id in sample_ids):
                elapsed = time.monotonic() - start_at
                samples.append((elapsed, line))
                print(f"IN_MOTION T={elapsed:.4f}s {line}", flush=True)
                if fields(line).get("FLT") != "0":
                    raise RuntimeError("Fault during motion; no automatic retry")
        # Never wait on more telemetry before commanding a stop.
        stop(board)
        if start_reply is None or not start_reply.startswith(f"{start_id} OK "):
            raise RuntimeError("START not acknowledged as queued")
        final = wait_for_idle(board)
        for elapsed, line in samples:
            print(f"SAMPLE T={elapsed:.4f}s CTRL={fields(line).get('CTRL')} POS={fields(line).get('POS')}", flush=True)
        before, after = position(baseline), position(final)
        if before is not None and after is not None:
            print(f"Position change: {after - before:+.2f} deg", flush=True)
    finally:
        if started:
            try:
                stop(board)
                wait_for_idle(board)
            except Exception as exc:
                print(f"SAFETY WARNING: STOP/IDLE unverified: {exc}", flush=True)
        for name in changed:
            try:
                value = original[name]
                board.command(f"SET {name} {value}")
                if fields(board.command(f"GET {name}")).get(name) != str(value):
                    raise RuntimeError("Readback differs from original")
            except Exception as exc:
                print(f"Restore {name} failed: {exc}", flush=True)
        if args.execute:
            try:
                print(board.command("ANALOG SAFE"), flush=True)
                safe = board.command("ANALOG SAFE STATUS")
                if not all(fields(safe).get(k) == v for k, v in
                           (("LATCHED", "1"), ("SD", "0"), ("MOE", "0"), ("FOC", "0"))):
                    raise RuntimeError("Power-off latch readback failed")
            except Exception as exc:
                print(f"SAFETY WARNING: bridge-off latch unverified: {exc}", flush=True)
        board.close()


if __name__ == "__main__":
    main()
