"""Offline decoder for ADC3PAR UART transcripts; no serial/SWD/hardware access.

Keep all raw triples. Any centered sum is a diagnostic arithmetic residual,
not a qualified phase-current value, EMI proof or an automatic fault override.
"""
import argparse
import json
import math
from pathlib import Path
import re
import statistics
import struct
import zlib

CAPACITY = 4096
BLOCK = 8


def fields(line):
    return dict(re.findall(r"\b([A-Z_]+)=([^\s]+)", line))


def require_status(line, terminal=False):
    if not re.match(r"^\d+ OK ADC3PAR ", line):
        raise ValueError("Not a three-phase status reply")
    row = fields(line)
    for key, value in (("CH", "3"), ("REAL_W", "1"), ("W_DELAY", "NONE"), ("SYNC", "COMMON_EVENT"),
                       ("W_ADC", "5"), ("W_PIN", "PA8"), ("W_READY", "1"),
                       ("LOCK", "1"), ("SD", "0"), ("MOE", "0"), ("CCER", "0"),
                       ("FOC", "0"), ("CAP", str(CAPACITY))):
        if row.get(key) != value:
            raise ValueError("Three-phase mode/output proof failed: " + key)
    if terminal:
        for key, value in (("STATE", "4"), ("REASON", "0"), ("CEN", "0"),
                           ("NU", "4096"), ("NV", "4096"), ("NW", "4096"),
                           ("IRQ", "1,1,1"), ("ERR", "0,0,0"), ("RESTORE", "1")):
            if row.get(key) != value:
                raise ValueError("Incomplete/failed capture: " + key)
        if not re.fullmatch(r"[0-9A-F]{8}", row.get("CRC", "")):
            raise ValueError("Missing full-capture CRC")
    return row


def decode_block(line, first):
    if not re.match(r"^\d+ OK ADC3PAR_DATA ", line):
        raise ValueError("Not a three-phase data reply")
    row = fields(line)
    if (first % BLOCK or not 0 <= first <= CAPACITY - BLOCK or
            row.get("I") != str(first) or row.get("N") != str(BLOCK) or
            not re.fullmatch(r"[0-9A-F]{96}", row.get("UVW", ""))):
        raise ValueError("Wrong index/block size/hex width")
    payload = row["UVW"]
    triples = [tuple(int(payload[i + k:i + k + 4], 16) for k in (0, 4, 8))
               for i in range(0, len(payload), 12)]
    if any(value > 4095 for triple in triples for value in triple):
        raise ValueError("Not 12-bit raw ADC data")
    return triples


def verify_capture(status, triples):
    row = require_status(status, terminal=True)
    if len(triples) != CAPACITY or any(len(t) != 3 for t in triples):
        raise ValueError("Expected all 4096 U/V/W triples")
    if any(not isinstance(v, int) or not 0 <= v <= 4095 for t in triples for v in t):
        raise ValueError("Invalid raw ADC value")
    crc = zlib.crc32(b"".join(struct.pack("<HHH", *t) for t in triples))
    if crc != int(row["CRC"], 16):
        raise ValueError("Whole-capture logical U/V/W CRC mismatch")
    return f"{crc:08X}"


def analyze(triples, zero_raw=None):
    if not triples or any(len(t) != 3 or any(not 0 <= v <= 4095 for v in t) for t in triples):
        raise ValueError("Expected nonempty valid raw triples")
    report = {"count": len(triples), "all_samples_retained": True,
              "common_trigger_three_independent_adcs": True, "sequential_rank_delay": False,
              "zero_aperture_skew_verified": False, "real_w_sampled": True,
              "motor_qualified": False, "signal_quality_qualified": False}
    for phase, name in enumerate("UVW"):
        values = [t[phase] for t in triples]
        report[name] = {"min": min(values), "max": max(values),
                        "mean": statistics.mean(values), "median": statistics.median(values),
                        "stddev": statistics.pstdev(values),
                        "max_adjacent_step": max((abs(b-a) for a, b in zip(values, values[1:])), default=0)}
    if zero_raw is not None:
        if (len(zero_raw) != 3 or any(not math.isfinite(v) or not 0 <= v <= 4095 for v in zero_raw)):
            raise ValueError("Three independent zero references required")
        # Same sign convention as existing code, with no forced sum=0 projection.
        residual = [sum(z-v for z, v in zip(zero_raw, t)) for t in triples]
        report["sum_residual_counts"] = {"zero_reference": list(zero_raw),
            "min": min(residual), "max": max(residual), "mean": statistics.mean(residual),
            "max_abs": max(map(abs, residual)), "diagnostic_only": True,
            "not_automatic_fault_override": True}
    return report


def read_transcript(text):
    status = None
    blocks = {}
    for line in text.splitlines():
        if re.match(r"^\d+ OK ADC3PAR ", line) and fields(line).get("STATE") == "4":
            require_status(line, terminal=True)
            if status is not None and fields(status)["CRC"] != fields(line)["CRC"]:
                raise ValueError("Mixed captures in transcript")
            status = line
        elif re.match(r"^\d+ OK ADC3PAR_DATA ", line):
            value = fields(line).get("I", "")
            if not value.isdigit():
                raise ValueError("Missing block index")
            first = int(value)
            if first in blocks:
                raise ValueError("Duplicate data block")
            blocks[first] = decode_block(line, first)
    if status is None or set(blocks) != set(range(0, CAPACITY, BLOCK)):
        raise ValueError("Missing terminal status or data blocks")
    triples = [t for first in range(0, CAPACITY, BLOCK) for t in blocks[first]]
    return status, triples, verify_capture(status, triples)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("transcript", type=Path)
    parser.add_argument("--zero-raw", nargs=3, type=float)
    args = parser.parse_args()
    status, triples, crc = read_transcript(args.transcript.read_text(encoding="utf-8-sig"))
    print(json.dumps({"status": status, "crc32": crc,
                      "report": analyze(triples, args.zero_raw)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
