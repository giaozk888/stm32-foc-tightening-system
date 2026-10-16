"""One bounded, explicitly authorized current-zero diagnostic acquisition.

Uses the already installed locked A/B diagnostic profile. Never flashes,
resets, unlocks outputs, clears faults or publishes motor offsets. The board
owns the 5 s acquisition limit; this host issues ZERO SAMPLE exactly once.
"""
import argparse
import json
import re
import time

from zero_retest_deploy import ROOT, DiagnosticUart, require_confirmed, require_service

ZERO_MAX_SPAN_COUNTS = 100


def require_confirmed_current(line):
    slot = fields(line).get("CURRENT")
    if slot not in ("A", "B"):
        raise RuntimeError("Need a known current slot")
    return require_confirmed(line, slot)


def fields(line):
    return dict(re.findall(r"\b([A-Z][A-Z0-9_]*)=([^\s]+)", line))


def require_supply(line):
    row = fields(line)
    if (row.get("VALID") != "1" or row.get("PROTECT") != "0" or
            not 10000 <= int(row.get("VBUS_EST_MV", "-1")) <= 14000 or
            not 3000 <= int(row.get("VDDA_BOOT_MV", "-1")) <= 3600 or
            not 0 <= int(row.get("AGE_MS", "-1")) <= 500):
        raise RuntimeError("Fresh analog supply estimate required; not physical supply proof")
    return row


def require_locked_sample(line):
    row = fields(line)
    if row.get("MEDIAN", "0") != "0":
        raise RuntimeError("Median contrast is not raw-zero qualification; use dedicated diagnostic tool")
    for key, value in (("PROFILE", "LOCKED_DIAGNOSTIC"), ("LOCK", "1"),
                       ("SD", "0"), ("MOE", "0"), ("CCER", "0"),
                       ("FOC", "0"), ("MOTOR_READY", "0"), ("IF", "0"),
                       ("ADC_READY", "1")):
        if row.get(key) != value:
            raise RuntimeError("Locked sample guard failed: " + line)
    if row.get("SPAN") != str(ZERO_MAX_SPAN_COUNTS):
        raise RuntimeError("Firmware span gate mismatch/missing; do not sample an old profile")
    state = row.get("STATE")
    if state in ("1", "2"):
        if row.get("ACTIVE") != "1" or row.get("CEN") != "1":
            raise RuntimeError("Active acquisition state contradicts timer")
    elif state in ("0", "3", "4"):
        if row.get("ACTIVE") != "0" or row.get("CEN") != "0":
            raise RuntimeError("Idle/terminal acquisition did not stop")
    else:
        raise RuntimeError("Unknown zero state")
    return row


def require_completed(line):
    row = require_locked_sample(line)
    if row.get("STATE") not in ("3", "4"):
        raise RuntimeError("Zero acquisition has not completed")
    if row["STATE"] == "3":
        nominal = int(row["NOM"])
        if (row.get("REASON") != "0" or row.get("N") != "4000" or
                row.get("SET") != "20000" or int(row["RET"]) >= 8 or
                int(row["ADC"]) < 24000):
            raise RuntimeError("READY lacks required bounded raw-sample evidence")
        for key in ("U0", "V0"):
            value = int(row[key])
            if not 1000 <= value <= 2200 or abs(value - nominal) > 100:
                raise RuntimeError("READY zero outside nominal gate")
        for limits in row["RNG"].split(","):
            low, high = map(int, limits.split(":"))
            if low > high or high - low > ZERO_MAX_SPAN_COUNTS:
                raise RuntimeError("READY span exceeds configured gate")
    elif row.get("U0") != "0" or row.get("V0") != "0":
        raise RuntimeError("Failed zero must not publish offsets")
    return row


class OneShotUart(DiagnosticUart):
    def __init__(self, port):
        super().__init__(port)
        self.sample_commands = 0

    def sample_once(self):
        if self.sample_commands:
            raise RuntimeError("No automatic repeated acquisition")
        self.sample_commands += 1
        self.request += 1
        self.port.write(f"{self.request} ZERO SAMPLE\r\n".encode("ascii"))
        deadline = time.monotonic() + 1.5
        while time.monotonic() < deadline:
            line = self.read_line(.05)
            if line is not None:
                self.dispatch(line)
                if line.startswith(f"{self.request} "):
                    if not line.startswith(f"{self.request} OK "):
                        raise RuntimeError(line)
                    return line
        raise TimeoutError("No sample ACK; do not resend; board timeout is independent")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--allow-zero-sample", action="store_true")
    parser.add_argument("--motor-leads-disconnected", action="store_true")
    parser.add_argument("--supply-12v-0p5a-no-alarm", action="store_true")
    args = parser.parse_args()
    if not all(vars(args).values()):
        parser.error("Explicit one-shot permission and physical conditions required")
    import serial
    directory = ROOT / "safety_backups/zero-span100-powered-20261009"
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / f"sample-{time.time_ns()}.json"
    result = {"acquisition_completed": False, "zero_qualified": False,
              "motor_qualified": False, "motion_commands": False,
              "reset": False, "flash_write": False, "thresholds_changed": False,
              "physical_conditions": "User confirmed motor U/V/W disconnected, 12 V/0.5 A, no alarm"}
    result["expected_span_counts"] = ZERO_MAX_SPAN_COUNTS
    port = serial.Serial(port=None, baudrate=115200, timeout=.02, write_timeout=1)
    port.dtr = port.rts = False
    port.port = "COM5"
    uart = OneShotUart(port)
    try:
        port.open()
        result["before_fw"] = require_confirmed_current(uart.query("FW STATUS", 3))
        slot = result["before_fw"]["CURRENT"]
        line = uart.query("ZERO STATUS")
        before = require_service(line)
        require_locked_sample(line)  # Verify the live gate before sending ZERO SAMPLE.
        if before.get("STATE") != "0" or before.get("ADC") != "0":
            raise RuntimeError("Need fresh unsampled diagnostic boot; do not reset automatically")
        result["before_zero"] = fields(line)
        result["supply"] = require_supply(uart.query("ANALOG VOLT"))
        started = time.monotonic()
        line = uart.sample_once()
        require_locked_sample(line)
        print(line, flush=True)
        while fields(line).get("STATE") not in ("3", "4"):
            if time.monotonic() - started > 7:
                raise TimeoutError("No terminal sample evidence; no retry/reset/unlock")
            time.sleep(.15)
            line = uart.query("ZERO STATUS")
            require_locked_sample(line)
            print(line, flush=True)
        result["terminal_zero"] = require_completed(line)
        result["seconds"] = round(time.monotonic() - started, 3)
        result["acquisition_completed"] = True
        result["zero_qualified"] = fields(line)["STATE"] == "3"
        for _ in range(10):
            time.sleep(.15)
            require_service(uart.query("ZERO STATUS"))
        result["after_fw"] = require_confirmed(uart.query("FW STATUS"), slot)
        if result["after_fw"]["GEN"] != result["before_fw"]["GEN"]:
            raise RuntimeError("Unexpected boot metadata change")
        result["output_stopped_after_sampling"] = True
        print("ZERO DIAGNOSTIC " + ("READY" if result["zero_qualified"] else "FAILED") +
              "; outputs stopped; motor NOT qualified", flush=True)
    except Exception as error:
        result["failure"] = str(error)
        raise
    finally:
        result["sample_commands"] = uart.sample_commands
        result["uart"] = uart.lines
        port.close()
        target.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print("Evidence: " + str(target), flush=True)


if __name__ == "__main__":
    main()
