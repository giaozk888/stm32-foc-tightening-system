"""Analyze ADC SPREAD diagnostics without connecting to a board.

Only paired U/V blocks with MIX=0 are accepted. Standard deviation is raw-code
spread, not switching-noise isolation or current-accuracy calibration.
"""
from __future__ import annotations
import argparse
import json
import math
import re
from pathlib import Path


def analyze(text: str) -> dict:
    records: dict[tuple[int, str], dict] = {}
    rejected: list[dict] = []
    for line in text.splitlines():
        match = re.search(r"OK ADC SPREAD ([UV])\s+(.*)", line)
        if not match:
            continue
        values = {k: int(v) for k, v in re.findall(r"(\w+)=(\d+)", match[2])}
        required = {"B", "N", "SUM", "SS", "MIN", "MAX", "STEP", "MIX",
                    "CMDU", "CMDV", "CMDW", "CMD4"}
        if not required <= values.keys():
            rejected.append({"reason": "missing_fields"})
            continue
        key = (values["B"], match[1])
        if key in records:
            if records[key] != values:
                raise ValueError(f"Conflicting duplicate block {key}")
            continue
        records[key] = values
    blocks = []
    for block in sorted({key[0] for key in records}):
        pair = [records.get((block, ch)) for ch in "UV"]
        if any(p is None for p in pair):
            rejected.append({"block": block, "reason": "unpaired_uv"})
            continue
        assert pair[0] is not None and pair[1] is not None
        if any(p["MIX"] for p in pair):
            rejected.append({"block": block, "reason": "changing_command_registers"})
            continue
        window_keys = ("N", "CMDU", "CMDV", "CMDW", "CMD4")
        if any(pair[0][key] != pair[1][key] for key in window_keys):
            rejected.append({"block": block, "reason": "uv_metadata_mismatch"})
            continue
        channels = {}
        for ch, p in zip("UV", pair):
            n = p["N"]
            if n != 256 or not (0 <= p["MIN"] <= p["MAX"] <= 4095):
                raise ValueError(f"Invalid block geometry {block} {ch}")
            if not (n * p["MIN"] <= p["SUM"] <= n * p["MAX"]):
                raise ValueError(f"Invalid raw sum {block} {ch}")
            if not (n * p["MIN"]**2 <= p["SS"] <= n * p["MAX"]**2):
                raise ValueError(f"Invalid raw sum-square {block} {ch}")
            variance_numerator = n * p["SS"] - p["SUM"]**2
            if variance_numerator < 0:
                raise ValueError(f"Negative variance {block} {ch}")
            channels[ch] = {
                "mean_counts": p["SUM"] / n,
                "population_stddev_counts": math.sqrt(variance_numerator) / n,
                "peak_to_peak_counts": p["MAX"] - p["MIN"],
                "max_step_counts": p["STEP"],
            }
        blocks.append({"block": block, "command_registers_not_active_shadow":
                       {k: pair[0][k] for k in window_keys}, "channels": channels})
    return {"accepted_blocks": blocks, "rejected_blocks": rejected,
            "physical_conditions_verified": False,
            "scope": "raw ADC spread only; no accuracy/noise-reduction claim"}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("log", type=Path)
    parser.add_argument("--evidence", choices=("synthetic", "measured"), required=True)
    args = parser.parse_args()
    result = analyze(args.log.read_text(encoding="utf-8", errors="replace"))
    result["evidence_label_supplied_by_caller"] = args.evidence
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
