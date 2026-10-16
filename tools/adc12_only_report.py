"""Locked ADC1/2 contrast decoder; W is zero padding, not a measurement."""
import re
import statistics
import struct
import zlib
from adc_parallel_report import CAPACITY, fields


def require_status(line, terminal=False):
    if not re.match(r"^\d+ OK ADC3PAR ", line):
        raise ValueError("Missing ADC1/2-only reply")
    row = fields(line)
    required = {"MODE": "ADC12_ONLY", "CAPTURE_MASK": "3", "CH": "2", "REAL_W": "0",
                "PAD_W": "ZERO_UNSAMPLED", "SYNC": "COMMON_EVENT", "W_READY": "1",
                "LOCK": "1", "SD": "0", "MOE": "0", "CCER": "0", "FOC": "0",
                "CAP": str(CAPACITY), "SMP_CYCLES": "247.5"}
    if terminal:
        required.update(STATE="4", REASON="0", CEN="0", NU="4096", NV="4096", NW="0",
                        IRQ="1,1,0", ERR="0,0,0", RESTORE="1", SMP_CHECK="3")
    for key, value in required.items():
        if row.get(key) != value:
            raise ValueError("ADC1/2 identity/lock/capture proof failed: " + key)
    if terminal and not re.fullmatch(r"[0-9A-F]{8}", row.get("CRC", "")):
        raise ValueError("Missing complete raw CRC")
    return row


def valid(triples):
    return bool(triples) and all(len(t) == 3 and t[2] == 0 and
        all(type(x) is int and 0 <= x <= 4095 for x in t[:2]) for t in triples)


def verify_capture(status, triples):
    row = require_status(status, terminal=True)
    if len(triples) != CAPACITY or not valid(triples):
        raise ValueError("All 4096 U/V 12-bit entries and unsampled zero W required")
    crc = zlib.crc32(b"".join(struct.pack("<HHH", *t) for t in triples))
    if crc != int(row["CRC"], 16):
        raise ValueError("Whole raw CRC mismatch")
    u, v = ([t[i] for t in triples] for i in (0, 1))
    if row.get("RANGE") != f"{min(u)}:{max(u)},{min(v)}:{max(v)},0:0":
        raise ValueError("Board min/max differs from complete raw payload")
    return f"{crc:08X}"


def analyze(triples):
    if not valid(triples):
        raise ValueError("Only measured U/V and zero W padding admitted")
    def stats(items):
        return {"count": len(items), "min": min(items), "max": max(items),
                "mean": statistics.mean(items), "median": statistics.median(items),
                "stddev": statistics.pstdev(items), "exact_2048": items.count(2048)}
    out = {"count": len(triples), "capture_mask": 3, "all_samples_retained": True,
           "common_trigger_three_independent_adcs": False, "common_trigger_adc1_adc2": True,
           "real_w_sampled": False, "W_unsampled_padding_only": True,
           "motor_qualified": False, "signal_quality_qualified": False}
    for i, name in enumerate(("U", "V")):
        values = [t[i] for t in triples]
        out[name] = stats(values)
        out[name + "_even_zero_based"] = stats(values[::2])
        out[name + "_odd_zero_based"] = stats(values[1::2])
    return out
