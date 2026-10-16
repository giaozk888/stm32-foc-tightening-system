"""Stable-zero isolated APP A observer. Default is read-only.

--commit-staged allows ONE FW END for the exact verified inactive image.
--allow-isolated-run allows bounded BENCH RUN/STOP and output-off cleanup.
No motion, fault-clear, parameter, boot-selection or forced confirmation.
"""
import argparse
import hashlib
import json
import re
import time
from pathlib import Path

from firmware_transfer_iap import Uart, ROOT, image_info
from powered_boot_probe import require_staged, read_staged_hardware_safe
from tighten_synthetic_acceptance import confirmed, locked, require_stopped

READ_COMMANDS = frozenset(("FW STATUS", "ANALOG SAFE STATUS", "STATUS",
    "SELFTEST STATUS", "FAULT SNAPSHOT", "FAULT FILTER", "ENC DIAG",
    "BENCH STATUS", "BENCH ZERO", "BENCH STACK"))
EXPECTED_SHA256 = "364577c5d22ba8a83baf6e0665f810cb260052a21afe4d9486056ca7ddeafe6f"

def fields(line):
    return dict(re.findall(r"\b([A-Za-z_][A-Za-z_0-9]*)=([^\s]+)", line))

def require_idle(line):
    status = fields(line)
    if any(status.get(k) != v for k, v in (("MODE", "IDLE"), ("BUSY", "0"),
        ("START_REQ", "0"), ("IqRef", "0mA"), ("FLT", "0"), ("REASON", "0"))):
        raise RuntimeError("Not idle/fault-free; never clear faults: " + line)

def require_zero(line):
    data = fields(line)
    if any(data.get(k) != v for k, v in (("STATE", "3"), ("REASON", "0"),
                                        ("N", "4000"), ("SET", "20000"))):
        raise RuntimeError("Stable raw-sample zero did not qualify: " + line)
    nominal = int(data["NOM"])
    if any(not 1000 <= int(data[k]) <= 2200 or abs(int(data[k])-nominal) > 100
           for k in ("U0", "V0")):
        raise RuntimeError("Qualified zero has unexpected range")
    ranges = re.fullmatch(r"(\d+):(\d+),(\d+):(\d+)", data.get("RNG", ""))
    if not ranges:
        raise RuntimeError("Missing raw window spread evidence")
    u_min, u_max, v_min, v_max = map(int, ranges.groups())
    if not 0 <= u_max-u_min <= 20 or not 0 <= v_max-v_min <= 20:
        raise RuntimeError("Accepted raw window spread exceeds gate")
    if not 0 <= int(data["RET"]) < 8:
        raise RuntimeError("Unexpected number of restarted windows")
    return data

def require_running(line):
    data = fields(line)
    if any(data.get(k) != v for k, v in (("ACTIVE", "1"), ("ZERO", "1"),
        ("LOCK", "1"), ("SD", "0"), ("MOE", "0"), ("CCER", "0"), ("CEN", "1"))):
        raise RuntimeError("Isolated computation is not active and locked: " + line)
    return data

class ZeroUart(Uart):
    def __init__(self, port, permit=False):
        super().__init__(port)
        self.request = 74000
        self.permit = permit
        self.lines = []

    def dispatch(self, line):
        if line:
            self.lines.append(line)
        if any(tag in line for tag in ("ISOLATED ZERO", "BOOT HEALTH:", "HardFault")):
            print(line, flush=True)

    def query(self, command, timeout=2):
        if command not in READ_COMMANDS and not (self.permit and command in
            ("BENCH RUN", "BENCH STOP", "ANALOG SAFE")):
            raise ValueError("Out-of-scope stable-zero command")
        self.request += 1
        request = self.request
        self.port.write(f"{request} {command}\r\n".encode("ascii"))
        deadline = time.monotonic()+timeout
        while time.monotonic() < deadline:
            line = self.read_line(min(.05, deadline-time.monotonic()))
            if line is None:
                continue
            self.dispatch(line)
            if line.startswith(f"{request} "):
                print(line, flush=True)
                if not line.startswith(f"{request} OK "):
                    raise RuntimeError(line)
                return line
        raise TimeoutError("No reply: " + command)

def observe_confirmed(uart, timeout=45):
    start = time.monotonic()
    deadline = start+timeout
    seen_a = False
    failed_zero = None
    while time.monotonic() < deadline:
        try:
            fw = fields(uart.query("FW STATUS", .75))
        except TimeoutError:
            continue
        if confirmed(fw, "A"):
            if failed_zero:
                raise RuntimeError("Calibration failure despite confirmation: " + failed_zero)
            return
        if confirmed(fw, "B") and (seen_a or time.monotonic()-start > 8):
            # The commit caller has already requested A. B now means rollback.
            raise RuntimeError("Existing bootloader returned to confirmed B" +
                               (": " + failed_zero if failed_zero else ""))
        if fw.get("CURRENT") == "A":
            seen_a = True
            zero = fields(uart.query("BENCH ZERO", 1))
            if zero.get("STATE") == "4" and failed_zero is None:
                failed_zero = str(zero)
                print("Calibration refused; observing existing health rollback, no retry", flush=True)
            state = uart.query("STATUS", 1)
            if not failed_zero:
                require_idle(state)
        until = min(deadline, time.monotonic()+.5)
        while time.monotonic() < until:
            uart.poll(.05)
    raise TimeoutError("A did not become health-confirmed; no forced confirmation")

def active_sample(uart):
    if not locked(fields(uart.query("ANALOG SAFE STATUS"))):
        raise RuntimeError("Output-off latch missing")
    require_idle(uart.query("STATUS"))
    return require_zero(uart.query("BENCH ZERO")), require_running(uart.query("BENCH STATUS"))

def measure(uart):
    zero, before = active_sample(uart)
    until = time.monotonic()+3.0
    while time.monotonic() < until:
        uart.poll(min(.05, until-time.monotonic()))
    after_zero, after = active_sample(uart)
    elapsed = int(after["MS"])-int(before["MS"])
    if elapsed < 2800:
        raise RuntimeError("Observation too short or bench restarted")
    rates = {k: (int(after[k])-int(before[k]))*1000.0/elapsed for k in ("ADC", "FOC")}
    if any(not 18000 <= hz <= 22000 for hz in rates.values()):
        raise RuntimeError("ADC/FOC rate outside 20 kHz tolerance: " + str(rates))
    if any(after_zero[k] != zero[k] for k in ("U0", "V0", "N", "RNG")):
        raise RuntimeError("Published zero changed without recalibration")
    snapshot = fields(uart.query("FAULT SNAPSHOT"))
    if snapshot.get("VALID") != "0" or snapshot.get("REASON") != "0":
        raise RuntimeError("New current fault snapshot")
    stacks = fields(uart.query("BENCH STACK"))
    if any(int(stacks.get(k, "0")) < 256 for k in ("MOTOR", "ROUTER", "PROTO", "TRANSFER")):
        raise RuntimeError("Insufficient task stack margin")
    return {"zero": zero, "before": before, "after": after,
            "rates_hz": rates, "stacks": stacks}

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", default="COM5")
    parser.add_argument("--image", type=Path, default=ROOT/"foc2_app_a/build/StableZeroIsolated/foc2.bin")
    parser.add_argument("--commit-staged", action="store_true")
    parser.add_argument("--allow-isolated-run", action="store_true")
    parser.add_argument("--output", type=Path, default=ROOT/"safety_backups/stable-zero-live-20261008")
    args = parser.parse_args()
    output = args.output.resolve()
    if not output.is_relative_to((ROOT/"safety_backups").resolve()):
        parser.error("Evidence must stay within safety_backups")
    image = args.image.read_bytes()
    if image_info(image)[0] != "A" or hashlib.sha256(image).hexdigest() != EXPECTED_SHA256:
        parser.error("Only the exact offline-verified isolated A image is allowed")
    record = {"passed": False, "image_sha256": EXPECTED_SHA256,
              "motion_commands": False, "forced_confirmation": False,
              "fault_clearing": False, "runs": []}
    target = output/f"board-observation-{time.time_ns()}.json"
    import serial
    port = serial.Serial(port=None, baudrate=115200, timeout=.02, write_timeout=1)
    port.dtr = port.rts = False
    port.port = args.port
    uart = None
    mutating = args.commit_staged or args.allow_isolated_run
    try:
        port.open()
        uart = ZeroUart(port, permit=mutating)
        fw_line = uart.query("FW STATUS")
        if args.commit_staged:
            require_staged(fw_line, read_staged_hardware_safe(), image)
            record["commit_attempted"] = True
            # A lost commit ACK is never retried. Observe the existing trial.
            try:
                uart.command("FW END", 3)
            except TimeoutError:
                print("FW END ACK uncertain; observing once, not retrying", flush=True)
            observe_confirmed(uart)
        elif not confirmed(fields(fw_line), "A"):
            raise RuntimeError("Read-only observer requires confirmed isolated A")

        record["runs"].append(measure(uart))
        if args.allow_isolated_run:
            # Two warm requalifications, each stopped after a short observation.
            for _ in range(2):
                require_stopped(uart.query("BENCH STOP"))
                require_idle(uart.query("STATUS"))
                uart.query("BENCH RUN")
                deadline = time.monotonic()+5.2
                while time.monotonic() < deadline:
                    zero = fields(uart.query("BENCH ZERO"))
                    if zero.get("STATE") == "4":
                        raise RuntimeError("Repeated raw-sample zero failed: " + str(zero))
                    if zero.get("STATE") == "3":
                        break
                    until = min(deadline, time.monotonic()+.2)
                    while time.monotonic() < until:
                        uart.poll(.05)
                else:
                    raise TimeoutError("Repeated qualification deadline exceeded")
                record["runs"].append(measure(uart))
        record["passed"] = True
    except BaseException as error:
        record["failure"] = str(error)
        raise
    finally:
        if uart is not None and mutating:
            try:
                state = fields(uart.query("FW STATUS"))
                if state.get("CURRENT") == "A":
                    require_stopped(uart.query("BENCH STOP"))
                elif state.get("CURRENT") == "B":
                    # Existing fallback APP can start its normal zero-current
                    # control; explicitly latch it off as soon as UART returns.
                    uart.query("ANALOG SAFE")
                else:
                    raise RuntimeError("Unknown final slot")
                if not locked(fields(uart.query("ANALOG SAFE STATUS"))):
                    raise RuntimeError("Final output-off latch did not verify")
                record["final_fw"] = fields(uart.query("FW STATUS"))
                record["final_status"] = fields(uart.query("STATUS"))
                record["final_zero"] = fields(uart.query("BENCH ZERO")) if state.get("CURRENT") == "A" else None
                record["final_safe_locked"] = True
            except BaseException as error:
                record["passed"] = False
                record["cleanup_failure"] = str(error)
                print("SAFETY WARNING: final state unverified; keep drive power physically isolated: " + str(error), flush=True)
        if uart is not None:
            record["uart_lines"] = uart.lines
        port.close()
        output.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(record, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
        print("Evidence: " + str(target), flush=True)
    if not record["passed"]:
        raise RuntimeError("Stable zero was not accepted")
    print("STABLE ZERO BOARD PASS: raw windows, 20kHz computation, warm repeatability, outputs locked off. NOT industrial current/torque certification.", flush=True)

if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, RuntimeError, TimeoutError) as error:
        raise SystemExit("STABLE ZERO FAILED: " + str(error))
