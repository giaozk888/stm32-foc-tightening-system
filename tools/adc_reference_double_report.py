"""Offline-only 8192-pair GPIO-low known-input decoder. No device access.

Do not use legacy 4096 evidence to qualify a longer capture. W is export
padding, and grounded/reference inputs do not qualify motor current feedback.
"""
import re
import struct
import zlib
from adc_reference_report import require_status as legacy_status
from adc12_only_report import analyze
from zero_retest_sample import fields

CAPACITY = 8192
BLOCK = 8


def require_status(line, terminal=False, power=None):
    row = fields(line)
    required = {"CAP": str(CAPACITY), "WINDOW": "DOUBLE", "RAW_STORAGE": "UV_ONLY",
                "PIN_POLICY": "GPIO_LOW", "PIN_CFG": "1", "PIN_LEVEL": "1"}
    if not re.match(r"^\d+ OK ADC3PAR ", line) or any(row.get(k) != v for k, v in required.items()):
        raise ValueError("Exact 8192-pair GPIO-low double-window identity required")
    if terminal and any(row.get(k) != str(CAPACITY) for k in ("NU", "NV")):
        raise ValueError("Incomplete extended capture")
    # Validate unchanged supply/lock/IRQ/ADC identity with legacy validator;
    # actual lengths are checked above and never discarded during CRC checks.
    normalized = re.sub(r"\b(CAP|NU|NV)=8192\b", r"\1=4096", line)
    legacy_status(normalized, terminal=terminal, power=power)
    if terminal and not 390 <= int(row.get("MS", "-1")) <= 999:
        raise ValueError("Extended capture duration outside bounded nominal window")
    return row


def decode_block(line, first):
    row = fields(line)
    if (not re.match(r"^\d+ OK ADC3PAR_DATA ", line) or first % BLOCK or
            not 0 <= first <= CAPACITY-BLOCK or row.get("I") != str(first) or
            row.get("N") != str(BLOCK) or not re.fullmatch(r"[0-9A-F]{96}", row.get("UVW", ""))):
        raise ValueError("Invalid extended block index or payload")
    data = row["UVW"]
    triples = [tuple(int(data[i+k:i+k+4], 16) for k in (0, 4, 8)) for i in range(0, 96, 12)]
    if any(u > 4095 or v > 4095 or w != 0 for u, v, w in triples):
        raise ValueError("Invalid raw value or fabricated W sample")
    return triples


def verify_capture(line, triples, power=None):
    row = require_status(line, terminal=True, power=power)
    if (len(triples) != CAPACITY or any(len(t) != 3 or
            any(type(v) is not int or not 0 <= v <= 4095 for v in t) or t[2] != 0 for t in triples)):
        raise ValueError("All 8192 genuine U/V pairs and zero W padding required")
    ranges = ",".join(f"{min(t[p] for t in triples)}:{max(t[p] for t in triples)}" for p in range(3))
    if row.get("RANGE") != ranges:
        raise ValueError("Full extended ranges differ")
    crc = zlib.crc32(b"".join(struct.pack("<HHH", *t) for t in triples))
    if f"{crc:08X}" != row["CRC"]:
        raise ValueError("Whole extended logical triple CRC mismatch")
    return f"{crc:08X}"
