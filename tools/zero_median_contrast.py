"""Exact median/raw contrast deployment or single sample. Never motor-ready.

deploy inherits the official Transfer and bootloader confirmation protocol;
sample never resets, flashes, unlocks or retries. Deployment accepts only the
known locked A and exact uncommitted 4 A B, preserving A as the fallback.
"""
import hashlib
import json
import re
import sys
import time
import zlib
from pathlib import Path
import adc_parallel_acceptance as deploy
import zero_async_clock_sample as sample
from zero_retest_deploy import latest_meta, require_service
from zero_retest_sample import fields, require_locked_sample, require_completed, OneShotUart
from zero_span100_acceptance import require_new_service
from zero_injected_control_acceptance import (
    ROOT, PINNED as RAW_PINNED, PATH_ADDRESSES, require_injected_registers,
)
from phase_current_4a_stage import target_image

PROFILE = "ZERO_MEDIAN_CONTRAST_20261012"
OUTPUT = ROOT / "safety_backups/zero-median-contrast-20261012"
PINNED = {"A": RAW_PINNED["A"],
          "B": "de086d613ee504e792ec67d7119afee0039306852776f7850c22818944cf6eff"}


def image(slot):
    directory = "ZeroInjectedControlOff20261012" if slot == "A" else "ZeroMedianContrast20261012"
    path = ROOT / f"foc2_app_{slot.lower()}/build/{directory}/foc2.bin"
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != PINNED[slot]:
        raise RuntimeError("Exact known locked image required")
    if slot == "B" and b"MEDIAN=1" not in data:
        raise RuntimeError("Missing median diagnostic marker")
    return path, data


def baseline(data):
    if len(data) != 0x80000:
        raise RuntimeError("Complete protected baseline required")
    meta = latest_meta(data)
    if meta[2:6] != (1, 0, 0, 405):
        raise RuntimeError("Only confirmed locked A with no pending trial admitted")
    _, a = image("A")
    _, b = target_image()
    if (data[0x8000:0x8000+len(a)] != a or data[0x40000:0x40000+len(b)] != b or
            meta[6:8] != (len(a), zlib.crc32(a))):
        raise RuntimeError("Only exact locked A and known uncommitted 4 A B admitted")
    return {"current": "A", "generation": meta[5],
            "inactive_b_uncommitted_4a": True, "fallback_a_exact_locked": True}


def fresh(uart):
    line = uart.query("ZERO STATUS")
    row = require_new_service(line)
    if row.get("MEDIAN") != "1" or row.get("ADC_OWNER") != "1":
        raise RuntimeError("Fresh median contrast marker required")
    return {"zero": row}


def median_guard(line):
    if fields(line).get("MEDIAN") != "1":
        raise RuntimeError("Only explicit median contrast may use this validator")
    # All output/timer/zero gates remain the same. Only the explicit marker is
    # removed for the raw validator; the caller records the unmodified fields.
    require_locked_sample(re.sub(r"\bMEDIAN=1\s*", "", line))
    return fields(line)


def terminal(line):
    median_guard(line)
    require_completed(re.sub(r"\bMEDIAN=1\s*", "", line))
    return fields(line)


def fresh_sample(line):
    require_service(line)
    median_guard(line)
    row = fields(line)
    if any(row.get(k) != v for k, v in (("STATE", "0"), ("ADC", "0"),
                                       ("N", "0"), ("REASON", "0"), ("U0", "0"), ("V0", "0"))):
        raise RuntimeError("Need fresh, unsampled median contrast; no automatic reset")
    return row


def handover(record):
    if record.get("profile") != PROFILE or record.get("target_slot") != "B":
        raise RuntimeError("Exact normally deployed B median contrast required")
    require_injected_registers("\n".join(f"{a} : {v}" for a, v in record.get("async_clock_registers", {}).items()))
    return sample.require_handover(record, image_hashes=PINNED)


def filter_status(line):
    row = fields(line)
    if row.get("MEDIAN") != "1" or row.get("MOTOR_READY") != "0":
        raise RuntimeError("Missing diagnostic-only raw/filter evidence")
    required = ("PAIRS", "CHANGED", "OUT", "RAW_STATE", "RAW_REASON", "RAW_N",
                "RAW_U0", "RAW_V0", "RAW_LAST", "RAW_RANGE", "FILTER_STATE", "FILTER_REASON")
    if any(k not in row for k in required):
        raise RuntimeError("Incomplete raw/filter contrast evidence")
    if row["FILTER_STATE"] not in ("3", "4") or row["RAW_STATE"] not in ("1", "2", "3", "4"):
        raise RuntimeError("Contrast not completed")
    if int(row["CHANGED"]) > int(row["PAIRS"]) or int(row["OUT"]) > int(row["PAIRS"]):
        raise RuntimeError("Invalid contrast counters")
    if row["RAW_STATE"] == "4" and (row["RAW_U0"] != "0" or row["RAW_V0"] != "0"):
        raise RuntimeError("Raw failure published partial zeros")
    return row


class MedianUart(OneShotUart):
    def query(self, command, timeout=1):
        if command != "ZERO FILTER STATUS":
            return super().query(command, timeout)
        self.request += 1
        self.port.write(f"{self.request} {command}\r\n".encode("ascii"))
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            line = self.read_line(.05)
            if line is None:
                continue
            self.dispatch(line)
            if line.startswith(f"{self.request} "):
                if not line.startswith(f"{self.request} OK "):
                    raise RuntimeError(line)
                return line
        raise TimeoutError("No filter status response; no resampling")


def main():
    if len(sys.argv) < 2 or sys.argv[1] not in ("deploy", "sample"):
        raise SystemExit("Select deploy or sample with explicit inherited authorization flags")
    mode = sys.argv.pop(1)
    if mode == "deploy":
        deploy.main(image_provider=image, baseline_checker=baseline, fresh_checker=fresh,
                    image_hashes=PINNED, output_dir=OUTPUT, profile=PROFILE,
                    clock_addresses=PATH_ADDRESSES, clock_checker=require_injected_registers)
    else:
        sample.main(handover_checker=handover, image_hashes=PINNED, output_dir=OUTPUT,
                    clock_addresses=PATH_ADDRESSES, clock_checker=require_injected_registers,
                    fresh_checker=fresh_sample, sample_label="MEDIAN FILTER CONTRAST",
                    sample_guard=median_guard, terminal_checker=terminal, uart_factory=MedianUart,
                    filtered_diagnostic_only=True, extra_status_query="ZERO FILTER STATUS",
                    extra_status_checker=filter_status)


if __name__ == "__main__":
    main()
