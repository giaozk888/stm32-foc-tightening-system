"""Isolated CPU-only fixture acceptance. No motor, parameter or Flash commands.

Default: read-only. --commit-staged separately permits FW END of an EXACT
already-staged inactive image. --allow-isolated-model permits BENCH STOP and
SIM RUN/STOP after confirmed hard isolation. Never force boot confirmation.
"""
import argparse
import json
from pathlib import Path
import re
import subprocess
import time

from firmware_transfer_iap import Uart, fields, image_info, ROOT
from powered_boot_probe import require_staged, read_staged_hardware_safe


class SyntheticUart(Uart):
    def __init__(self, port):
        super().__init__(port)
        self.request = 62000
        self.evidence = []
        self.boot_messages = []
        self.uart_lines = []

    def dispatch(self, line):
        if line:
            self.uart_lines.append(line)
        if any(s in line for s in ("BOOT HEALTH:", "SYNTHETIC FIXTURE", "ISOLATED CONCURRENCY:")):
            self.boot_messages.append(line)
            print(line, flush=True)
        if any(s in line for s in ("CREATE FAILED", "HardFault", "ISOLATED BENCH START FAILED",
                                   "AS5047P STARTUP CHECK FAILED", "ADC1 hardware calibration FAILED",
                                   "ADC2 hardware calibration FAILED")):
            raise RuntimeError("Startup refused: " + line)

    def query(self, text, timeout=3):
        if not re.fullmatch(r"FW STATUS|ANALOG SAFE(?: STATUS)?|SELFTEST STATUS|STATUS|"
                            r"FAULT (SNAPSHOT|FILTER)|ENC DIAG|"
                            r"BENCH (STATUS|STACK|STOP)|SIM (STATUS|RUN|STOP|RESULT [0-9]+ [01])", text):
            raise ValueError("Out-of-scope synthetic test command")
        self.request += 1
        self.port.write(f"{self.request} {text}\r\n".encode("ascii"))
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            line = self.read_line(min(0.1, deadline - time.monotonic()))
            if line is None:
                continue
            self.dispatch(line)
            if line.startswith(f"{self.request} "):
                self.evidence.append(line)
                print(line, flush=True)
                if not line.startswith(f"{self.request} OK "):
                    raise RuntimeError(line)
                return line
        raise TimeoutError("No synthetic ACK: " + text)


def confirmed(fw, slot):
    return slot in ("A", "B") and all(fw.get(k) == v for k, v in (
        ("CURRENT", slot), ("CONFIRMED", slot), ("PENDING", "-"),
        ("ATTEMPTS", "0"), ("ACTIVE", "0"), ("HTRIAL", "0")))


def locked(safe):
    return all(safe.get(k) == v for k, v in (
        ("LATCHED", "1"), ("SD", "0"), ("MOE", "0"), ("FOC", "0")))


def rollback_detected(fw, expected_slot):
    return fw.get("CURRENT") != expected_slot and confirmed(fw, fw.get("CURRENT"))


def require_stopped(line):
    f = fields(line)
    if any(f.get(k) != v for k, v in (
            ("ACTIVE", "0"), ("LOCK", "1"), ("SD", "0"), ("MOE", "0"), ("CCER", "0"), ("CEN", "0"))):
        raise RuntimeError("Synthetic model needs stopped hard isolation")


def host_results(executable):
    completed = subprocess.run([str(executable)], capture_output=True, text=True, check=True, timeout=20)
    results = {}
    for line in completed.stdout.splitlines():
        if line.startswith("CASE="):
            row = fields(line)
            key = (int(row["CASE"]), int(row["MODE"]))
            if key in results:
                raise RuntimeError("Duplicate native host case")
            results[key] = row
    if set(results) != {(i, m) for i in range(12) for m in range(2)}:
        raise RuntimeError("Need all 24 host cases")
    return results


def compare_case(board, host):
    for key in ("OUT", "TARGET", "TRUTH", "TRANS", "OFF", "MODEL", "MAXMA"):
        if board.get(key) != host.get(key):
            raise RuntimeError("Board/host mismatch: " + key)
    if abs(int(board["MS"]) - int(host["MS"])) > 20:
        raise RuntimeError("Board/host modeled elapsed difference exceeds 20 ms")
    if abs(int(board["STEPS"]) - int(host["STEPS"])) > 40:
        raise RuntimeError("Board/host step difference exceeds 40")
    for key in ("FINAL", "PEAK"):
        if abs(int(board[key]) - int(host[key])) > 20000:
            raise RuntimeError("Board/host float32 difference exceeds 20000 nN.m")


def run_model(uart, slot, reference):
    if not confirmed(fields(uart.query("FW STATUS")), slot):
        raise RuntimeError("Need a confirmed slot before synthetic execution")
    if not locked(fields(uart.query("ANALOG SAFE STATUS"))):
        raise RuntimeError("Power stage not latched off")
    state = fields(uart.query("STATUS"))
    if any(state.get(k) != v for k, v in (("MODE", "IDLE"), ("BUSY", "0"), ("FLT", "0"), ("REASON", "0"))):
        raise RuntimeError("Existing fault/busy state; do not clear it")
    require_stopped(uart.query("BENCH STOP"))
    require_stopped(uart.query("BENCH STATUS"))
    start = fields(uart.query("SIM RUN"))
    if start.get("BUSY") != "1" or start.get("MODEL") != "1" or start.get("LOCK") != "1":
        raise RuntimeError("Synthetic run was not admitted")
    deadline = time.monotonic() + 125
    while time.monotonic() < deadline:
        time.sleep(0.25)
        status = fields(uart.query("SIM STATUS"))
        if status.get("LOCK") != "1" or status.get("MODEL") != "1" or status.get("FAIL") != "0":
            raise RuntimeError("Synthetic fixture safety/result failure")
        if status.get("BUSY") == "0":
            break
    else:
        raise TimeoutError("Synthetic fixture wall-clock timeout")
    if status.get("DONE") != "24" or status.get("PASS") != "24" or int(status["STACK"]) < 512:
        raise RuntimeError("Incomplete cases or inadequate synthetic stack margin")
    results = []
    for case in range(12):
        for mode in range(2):
            row = fields(uart.query(f"SIM RESULT {case} {mode}"))
            if row.get("CASE") != str(case) or row.get("MODE") != str(mode):
                raise RuntimeError("Wrong result identity")
            compare_case(row, reference[(case, mode)])
            results.append(row)
    require_stopped(uart.query("BENCH STATUS"))
    if not locked(fields(uart.query("ANALOG SAFE STATUS"))):
        raise RuntimeError("Final power-off check failed")
    if not confirmed(fields(uart.query("FW STATUS")), slot):
        raise RuntimeError("Final slot state changed")
    uart.query("STATUS")
    uart.query("BENCH STACK")
    return status, results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", default="COM5")
    parser.add_argument("--image", type=Path, required=True)
    parser.add_argument("--host", type=Path, default=ROOT / "tests/tighten_synthetic_host/build/tighten_synthetic_test.exe")
    parser.add_argument("--output", type=Path, default=ROOT / "safety_backups/tighten-synthetic-20261008")
    parser.add_argument("--commit-staged", action="store_true")
    parser.add_argument("--observe-trial", action="store_true", help="read-only wait for an already requested trial")
    parser.add_argument("--allow-isolated-model", action="store_true")
    args = parser.parse_args()
    image = args.image.read_bytes()
    slot, crc = image_info(image)
    output = args.output.resolve()
    if not output.is_relative_to((ROOT / "safety_backups").resolve()):
        parser.error("Output must stay inside workspace safety_backups")
    reference = host_results(args.host.resolve()) if args.allow_isolated_model else {}
    import serial
    port = serial.Serial(port=None, baudrate=115200, timeout=0.02, write_timeout=1)
    port.dtr = port.rts = False
    port.port = args.port
    uart = None
    running = False
    failure = None
    try:
        port.open()
        uart = SyntheticUart(port)
        try:
            fw = uart.query("FW STATUS")
        except TimeoutError:
            if not args.observe_trial:
                raise
            fw = ""
        if args.commit_staged:
            # Staging firmware sometimes rejects non-FW queries. Read actual
            # SD/MOE/CEN over HOTPLUG before committing, never bypass isolation.
            safe = read_staged_hardware_safe()
            require_staged(fw, safe, image)
            uart.command("FW END", timeout=20)
        if args.commit_staged or args.observe_trial:
            deadline = time.monotonic() + 45
            while time.monotonic() < deadline:
                try:
                    fw = uart.query("FW STATUS", timeout=1)
                except TimeoutError:
                    continue
                if confirmed(fields(fw), slot):
                    print("EXISTING BOOT HEALTH CONFIRMED " + slot, flush=True)
                    break
                if rollback_detected(fields(fw), slot):
                    # Only mutating acceptance modes may latch the fallback off.
                    # A read-only observer does not silently modify firmware state.
                    if args.commit_staged or args.allow_isolated_model:
                        if not locked(fields(uart.query("ANALOG SAFE"))):
                            raise RuntimeError("Rollback output lock did not verify")
                    raise RuntimeError("Bootloader rolled back; no forced confirmation/retry")
                time.sleep(0.4)
            else:
                raise RuntimeError("Trial not confirmed; no forced confirmation/retry")
        if not args.allow_isolated_model:
            print("NO MODEL RUN: no BENCH/SIM command sent", flush=True)
            return
        running = True
        status, results = run_model(uart, slot, reference)
        running = False
        payload = {
            "evidence_kind": "STM32_EXECUTED_SYNTHETIC_CPP_MODEL_ONLY",
            "industrial_accuracy_certified": False, "real_torque_measured": False,
            "physical_motor_commands": False, "flash_slot": slot, "image_crc32": f"{crc:08X}",
            "status": status, "results": results, "uart_evidence": uart.evidence,
            "boot_messages": uart.boot_messages,
            "host_parity_tolerance": {"modeled_ms": 20, "steps": 40, "torque_nnm": 20000},
        }
        output.mkdir(parents=True, exist_ok=True)
        (output / "board-results.json").write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print("BOARD SYNTHETIC PASS: 24/24; host parity; power outputs off; NOT real torque validation", flush=True)
    except BaseException as error:
        failure = str(error)
        raise
    finally:
        if running and uart is not None:
            try:
                uart.query("SIM STOP")
            except Exception:
                print("Cleanup: SIM STOP not acknowledged; inspect safe board state", flush=True)
        port.close()
        if failure is not None and uart is not None:
            output.mkdir(parents=True, exist_ok=True)
            payload = {"passed": False, "failure": failure, "expected_slot": slot,
                       "image_crc32": f"{crc:08X}", "model_may_have_started": running,
                       "uart_evidence": uart.evidence, "uart_lines": uart.uart_lines,
                       "industrial_accuracy_certified": False, "real_torque_measured": False}
            target = output / f"failed-observation-{time.time_ns()}.json"
            target.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            print("FAILURE EVIDENCE SAVED: " + str(target), flush=True)


if __name__ == "__main__":
    try:
        main()
    except (OSError, RuntimeError, ValueError, TimeoutError, subprocess.SubprocessError) as error:
        raise SystemExit("FAILED: " + str(error))
