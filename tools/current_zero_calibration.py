"""Observe real startup current-zero calibration in the existing normal B APP.

Read-only unless --execute is provided after on-site safety confirmation.
The only state-changing commands are one BOOT B and final ANALOG SAFE.
No START, firmware write, forced confirmation, parameter change or fault clear.
"""

import argparse
import math
import re
import time

from motor_motion_smoke import Board


READ_COMMANDS = frozenset((
    "FW STATUS", "ANALOG SAFE STATUS", "STATUS", "SELFTEST STATUS",
    "FAULT SNAPSHOT", "FAULT FILTER", "BENCH STATUS",
))


def fields(line):
    # STATUS contains mixed-case IqRef; the IAP-only parser omits that field.
    return dict(re.findall(r"\b([A-Za-z_]+)=([^\s]+)", line))


def require_source(fw_line, safe_line, status_line, health_line, bench_line):
    fw, safe, status, health, bench = map(
        fields, (fw_line, safe_line, status_line, health_line, bench_line))
    if any(fw.get(k) != v for k, v in (
            ("CURRENT", "A"), ("CONFIRMED", "A"), ("PENDING", "-"),
            ("ACTIVE", "0"), ("ATTEMPTS", "0"))):
        raise RuntimeError("Expected confirmed isolated A with no upgrade/trial")
    require_safe(safe_line)
    if any(status.get(k) != v for k, v in (
            ("MODE", "IDLE"), ("BUSY", "0"), ("START_REQ", "0"),
            ("IqRef", "0mA"), ("FLT", "1"), ("REASON", "1"))):
        raise RuntimeError("Source differs from the recorded isolated A fault")
    require_stationary(status_line)
    if health.get("ZERO") != "0" or any(bench.get(k) != v for k, v in (
            ("ACTIVE", "0"), ("LOCK", "1"), ("SD", "0"),
            ("MOE", "0"), ("CCER", "0"), ("CEN", "0"))):
        raise RuntimeError("Isolated source is not stopped/locked as expected")


def require_stationary(status_line):
    status = fields(status_line)
    for key in ("CTRL", "DET"):
        value = status.get(key, "")
        if not value.endswith("rpm"):
            raise RuntimeError("Missing speed feedback: " + key)
        speed = float(value[:-3])
        if not math.isfinite(speed) or abs(speed) >= 2.0:
            raise RuntimeError("Rotor is not stationary: " + status_line)


def require_safe(safe_line):
    safe = fields(safe_line)
    if any(safe.get(k) != v for k, v in (
            ("LATCHED", "1"), ("SD", "0"), ("MOE", "0"), ("FOC", "0"))):
        raise RuntimeError("Output-off latch is not verified")


def require_ready(fw_line, health_line, status_line):
    fw, health, status = map(fields, (fw_line, health_line, status_line))
    if any(fw.get(k) != v for k, v in (
            ("CURRENT", "B"), ("CONFIRMED", "B"), ("PENDING", "-"),
            ("ACTIVE", "0"), ("ATTEMPTS", "0"))):
        raise RuntimeError("Normal B is not confirmed/idle")
    if any(health.get(k) != v for k, v in (
            ("READY", "1"), ("MASK", "0x000"), ("ZERO", "1"),
            ("ADC", "1"), ("FOC", "1"), ("ENC", "1"))):
        raise RuntimeError("Real calibration/control-chain selftest failed")
    if any(status.get(k) != v for k, v in (
            ("MODE", "IDLE"), ("BUSY", "0"), ("START_REQ", "0"),
            ("IqRef", "0mA"), ("FLT", "0"), ("REASON", "0"))):
        raise RuntimeError("Normal B unexpectedly moved or faulted")
    require_stationary(status_line)


def calibration_evidence(lines):
    text = "\n".join(lines)
    if "ISOLATED DIGITAL BASELINE ONLY" in text:
        raise RuntimeError("Digital baseline cannot substitute for calibration")
    if "TWO ADC RUN ZERO CAL DONE" not in lines:
        raise RuntimeError("PWM-on calibration completion was not captured")
    static = re.search(r"STATIC ZERO\s*:\s*U=(\d+) V=(\d+)", text)
    run = re.search(r"RUN ZERO\s*:\s*U=(\d+) V=(\d+)", text)
    samples = re.search(r"VALID=(\d+) REJECTED=(\d+)", text)
    if not static or not run or not samples:
        raise RuntimeError("Incomplete calibration evidence")
    static_u, static_v = map(int, static.groups())
    run_u, run_v = map(int, run.groups())
    valid, rejected = map(int, samples.groups())
    if valid != 4000 or any(not 1000 <= v <= 2200 for v in (
            static_u, static_v, run_u, run_v)):
        raise RuntimeError("Calibration counts/range failed")
    if abs(run_u - static_u) > 100 or abs(run_v - static_v) > 100:
        raise RuntimeError("PWM-on zero shifted beyond the source sampling gate")
    return (static_u, static_v, run_u, run_v, valid, rejected)


class CalibrationBoard(Board):
    def __init__(self, port):
        self.lines = []
        super().__init__(port)
        self.next_id = 58000

    def send(self, command):
        if command not in READ_COMMANDS | {"BOOT B", "ANALOG SAFE"}:
            raise ValueError("Out-of-scope calibration command")
        print("TX " + command, flush=True)
        return super().send(command)

    def read_line(self, seconds=0.02):
        line = super().read_line(seconds)
        if line:
            self.lines.append(line)
            print("RX " + line, flush=True)
        return line


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", default="COM5")
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    board = CalibrationBoard(args.port)
    boot_attempted = False
    failure = None
    try:
        baseline = {name: board.command(name) for name in READ_COMMANDS}
        require_source(*(baseline[name] for name in (
            "FW STATUS", "ANALOG SAFE STATUS", "STATUS", "SELFTEST STATUS",
            "BENCH STATUS")))
        if not args.execute:
            print("READ-ONLY PASS; no reset, PWM or motion command sent", flush=True)
            return

        # A lost ACK must not trigger a second reset. Observe the one request.
        boot_attempted = True
        boot_id = board.send("BOOT B")
        deadline = time.monotonic() + 20.0
        startup_complete = False
        while time.monotonic() < deadline:
            line = board.read_line(0.05)
            if not line:
                continue
            if line.startswith(f"{boot_id} ERR "):
                raise RuntimeError("BOOT B was refused: " + line)
            if any(word in line for word in (
                    "ZERO CAL FAILED", "ZERO CAL ERROR", "ZERO CAL TIMEOUT",
                    "ZERO CAL INVALID", "hardware calibration FAILED",
                    "ENCODER READ FAILED", "STARTUP CHECK FAILED", "HardFault")):
                raise RuntimeError("Startup/calibration refused: " + line)
            if "StartupTask complete ->" in line:
                startup_complete = True
                break
        if not startup_complete:
            raise TimeoutError("Startup did not finish; no automatic reset/retry")

        zeros = calibration_evidence(board.lines)
        fw = board.command("FW STATUS")
        health = board.command("SELFTEST STATUS")
        status = board.command("STATUS")
        require_ready(fw, health, status)
        before = fields(health)

        # One short, zero-command observation for progress and no new fault.
        observe_until = time.monotonic() + 3.2
        while time.monotonic() < observe_until:
            board.read_line(min(0.05, observe_until - time.monotonic()))
        health = board.command("SELFTEST STATUS")
        status = board.command("STATUS")
        require_ready(board.command("FW STATUS"), health, status)
        after = fields(health)
        if (int(after["ADC_CNT"]) <= int(before["ADC_CNT"]) or
                int(after["FOC_CNT"]) <= int(before["FOC_CNT"])):
            raise RuntimeError("ADC/FOC counters did not progress")
        snapshot = fields(board.command("FAULT SNAPSHOT"))
        if snapshot.get("VALID") != "0" or snapshot.get("REASON") != "0":
            raise RuntimeError("New current fault snapshot after calibration")
        print("CALIBRATION EVIDENCE: STATIC_U=%d STATIC_V=%d RUN_U=%d "
              "RUN_V=%d VALID=%d REJECTED=%d" % zeros, flush=True)
    except BaseException as exc:
        failure = exc
    finally:
        if boot_attempted:
            try:
                # Idempotent power-off only; do not boot/reset again on failure.
                board.command("ANALOG SAFE", 2.0)
                require_safe(board.command("ANALOG SAFE STATUS"))
                final = board.command("STATUS")
                require_stationary(final)
                print("FINAL " + board.command("FW STATUS"), flush=True)
                print("OUTPUT-OFF VERIFIED: no START sent", flush=True)
            except BaseException as exc:
                print("SAFETY WARNING: power-off unverified; physically disconnect "
                      "drive power. " + str(exc), flush=True)
                if failure is None:
                    failure = exc
        board.close()
    if failure is not None:
        raise failure
    print("CURRENT ZERO CALIBRATION PASS; B remains latched safe. "
          "Offsets are RAM-only and must be recalibrated after reboot.", flush=True)


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, RuntimeError, TimeoutError) as error:
        raise SystemExit("CALIBRATION FAILED: " + str(error))
