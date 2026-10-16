"""Observe one original-parameter UART START cycle with an independent STOP guard.

Default mode checks preflight only. --execute runs one cycle; it does not
change recipe parameters. It latches ANALOG SAFE after a terminal outcome.
"""

import argparse
import re
import time

from motor_motion_smoke import Board, require_idle_ready, stop, wait_for_idle


PARAMS = (
    "RUNDOWN_RPM", "CONTACT_RPM", "CONTACT_IQ_MA", "CONTACT_MS",
    "RUNDOWN_TIMEOUT_MS", "MAX_TRAVEL_DEG", "SEATING_IQ_MA", "T1_IQ_MA",
    "T2_IQ_MA", "T3_IQ_MA", "HOLD_IQ_MA", "SEATING_MS", "T1_MS",
    "T2_MS", "T3_MS", "HOLD_MS", "TORQUE_ABORT_RPM",
    "POST_TRAVEL_MAX_DEG",
)


def field(line, name):
    match = re.search(rf"\b{name}=([-+]?\d+(?:\.\d+)?)", line)
    return float(match.group(1)) if match else None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", default="COM5")
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()

    board = Board(args.port)
    started = False
    terminal = False
    settled = False
    try:
        baseline = require_idle_ready(board)
        params = {}
        for name in PARAMS:
            line = board.command(f"GET {name}")
            value = field(line, name)
            if value is None:
                raise RuntimeError(f"Missing {name}")
            params[name] = int(value)
        if (params["RUNDOWN_TIMEOUT_MS"] > 8000
                or params["RUNDOWN_RPM"] > 70
                or params["MAX_TRAVEL_DEG"] > 3000
                or max(params[name] for name in
                       ("SEATING_IQ_MA", "T1_IQ_MA", "T2_IQ_MA",
                        "T3_IQ_MA", "HOLD_IQ_MA")) > 150):
            raise RuntimeError("Recipe exceeds the previously inspected bounds")
        print("ORIGINAL_RECIPE", params, flush=True)
        if not args.execute:
            print("READ-ONLY PASS; no motor command sent", flush=True)
            return

        baseline_pos = field(baseline, "POS")
        start_id = board.send("START")
        started = True
        start_at = time.monotonic()
        next_poll = start_at
        last_status = start_at
        active_seen = False
        start_ack = False
        pending_status = set()
        terminal_line = None

        while time.monotonic() - start_at < 15.0:
            now = time.monotonic()
            if now >= next_poll:
                pending_status.add(board.send("STATUS"))
                next_poll = now + 0.25
            line = board.serial.readline().decode("ascii", "replace").strip()
            if not line:
                if now - last_status > 1.5:
                    raise TimeoutError("STATUS telemetry stopped")
                continue
            if line.startswith(f"{start_id} "):
                print(line, flush=True)
                if not line.startswith(f"{start_id} OK START QUEUED"):
                    raise RuntimeError("START rejected")
                start_ack = True
            elif any(line.startswith(f"{req} ") for req in pending_status):
                request_id = int(line.split(" ", 1)[0])
                pending_status.discard(request_id)
                if " OK STATUS " not in line:
                    raise RuntimeError(line)
                last_status = now
                print(f"CYCLE t={now - start_at:.2f}s {line}", flush=True)
                speed = field(line, "CTRL")
                detect_speed = field(line, "DET")
                position = field(line, "POS")
                iqref = field(line, "IqRef")
                fault = field(line, "FLT")
                # CTRL is a 20 ms filtered estimator; allow brief cogging
                # excursions while also guarding the 50 ms speed estimate.
                if (fault != 0 or speed is None or abs(speed) > 150
                        or detect_speed is None or abs(detect_speed) > 120
                        or iqref is None or abs(iqref) > 450
                        or position is None or baseline_pos is None
                        or abs(position - baseline_pos) > 3200):
                    raise RuntimeError("Motion guard exceeded or fault detected")
                if "BUSY=1" in line or "MODE=SPD" in line or "MODE=IQ" in line:
                    active_seen = True
                if (active_seen and "BUSY=0" in line and "MODE=IDLE" in line
                        and "OUTCOME=NONE" not in line):
                    terminal = True
                    terminal_line = line
                    break
            elif line.startswith("T=") or line.startswith("TIGHTEN:"):
                # Periodic monitor lines contain measured Id/Iq and PI terms.
                print(f"MONITOR {line}", flush=True)

        if not start_ack or not active_seen or not terminal:
            raise TimeoutError("Full cycle did not reach a verified terminal state")
        print(f"TERMINAL {terminal_line}", flush=True)
        print(f"FINAL_STILL {wait_for_idle(board, 5.0)}", flush=True)
        settled = True
    finally:
        if started and not settled:
            try:
                stop(board)
                wait_for_idle(board, 5.0)
            except Exception as exc:
                print(f"SAFETY WARNING: STOP/IDLE unverified: {exc}", flush=True)
        if started:
            safe_error = None
            for _ in range(10):
                try:
                    print(board.command("ANALOG SAFE"), flush=True)
                    print(board.command("ANALOG SAFE STATUS"), flush=True)
                    safe_error = None
                    break
                except Exception as exc:
                    safe_error = exc
                    time.sleep(0.2)
            if safe_error is not None:
                print(f"SAFETY WARNING: bridge-off latch unverified: {safe_error}", flush=True)
        board.close()


if __name__ == "__main__":
    main()
