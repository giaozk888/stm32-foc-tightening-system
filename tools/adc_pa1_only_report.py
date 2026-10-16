"""Offline PA1-only contrast decoder. U/W are transport padding, NOT measurements."""
import re
import statistics
import struct
import zlib
from adc_parallel_report import CAPACITY, fields


def require_status(line, terminal=False):
    if not re.match(r"^\d+ OK ADC3PAR ", line):
        raise ValueError("Missing PA1-only diagnostic reply")
    row = fields(line)
    required = {"MODE": "PA1_ONLY", "CAPTURE_MASK": "2", "CH": "1", "REAL_W": "0",
                "PAD_UW": "ZERO_UNSAMPLED", "SYNC": "SINGLE", "W_READY": "1",
                "LOCK": "1", "SD": "0", "MOE": "0", "CCER": "0", "FOC": "0",
                "CAP": str(CAPACITY), "SMP_CYCLES": "247.5"}
    if terminal:
        required.update(STATE="4", REASON="0", CEN="0", NU="0", NV="4096", NW="0",
                        IRQ="0,1,0", ERR="0,0,0", RESTORE="1", SMP_CHECK="2")
    for key, value in required.items():
        if row.get(key) != value:
            raise ValueError("PA1-only identity/lock/capture proof failed: " + key)
    if terminal and not re.fullmatch(r"[0-9A-F]{8}", row.get("CRC", "")):
        raise ValueError("Missing complete raw CRC")
    return row


def verify_capture(status, triples):
    row = require_status(status, terminal=True)
    if len(triples) != CAPACITY or any(len(t) != 3 for t in triples):
        raise ValueError("All 4096 padded raw entries required")
    if any(t[0] != 0 or t[2] != 0 or not isinstance(t[1], int) or not 0 <= t[1] <= 4095 for t in triples):
        raise ValueError("U/W must be unsampled zero padding, PA1 must be a 12-bit integer")
    crc = zlib.crc32(b"".join(struct.pack("<HHH", *t) for t in triples))
    if crc != int(row["CRC"], 16):
        raise ValueError("Whole raw CRC mismatch")
    values = [t[1] for t in triples]
    if row.get("RANGE") != f"0:0,{min(values)}:{max(values)},0:0":
        raise ValueError("Board min/max differs from complete raw payload")
    return f"{crc:08X}"


def analyze(triples):
    if not triples or any(len(t) != 3 or t[0] or t[2] or not 0 <= t[1] <= 4095 for t in triples):
        raise ValueError("Only PA1 samples and zero transport padding admitted")
    values = [t[1] for t in triples]
    def stats(items):
        return {"count": len(items), "min": min(items), "max": max(items),
                "mean": statistics.mean(items), "median": statistics.median(items),
                "stddev": statistics.pstdev(items), "exact_2048": items.count(2048)}
    return {"count": len(values), "capture_mask": 2, "all_samples_retained": True,
            "common_trigger_three_independent_adcs": False, "real_w_sampled": False,
            "U_W_unsampled_padding_only": True, "motor_qualified": False,
            "signal_quality_qualified": False, "V": stats(values),
            "even_zero_based": stats(values[::2]), "odd_zero_based": stats(values[1::2])}
