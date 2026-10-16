from __future__ import annotations
import re

RANGES = {
    "seq": (0, 2**32-1), "uptime_ms": (0, 2**32-1), "run": (0, 2**32-1),
    "cycle": (0, 5), "stage": (0, 11), "outcome": (0, 6), "flags": (0, 127),
    "fault": (0, 65535), "position_cdeg": (-2**31, 2**31-1),
    "speed_drpm": (-2**31, 2**31-1), "iq_ma": (-2**31, 2**31-1),
    "vbus_mv": (0, 100000), "vbus_quality": (0, 31),
    "contact_cdeg": (-2**31, 2**31-1), "post_cdeg": (-2**31, 2**31-1),
    "kind": (0, 1),
}

def validate(value: object) -> dict:
    if not isinstance(value, dict) or set(value) != {"v", "device", "session", "sample"}:
        raise ValueError("invalid envelope")
    if type(value["v"]) is not int or value["v"] != 1:
        raise ValueError("unsupported version")
    for key, pattern in (("device", r"[0-9A-F]{12}"), ("session", r"[0-9A-F]{16}")):
        if not isinstance(value[key], str) or not re.fullmatch(pattern, value[key]):
            raise ValueError(f"invalid {key}")
    s = value["sample"]
    if not isinstance(s, dict) or set(s) != set(RANGES):
        raise ValueError("invalid sample fields")
    for key, (lo, hi) in RANGES.items():
        if type(s[key]) is not int or not lo <= s[key] <= hi:
            raise ValueError(f"invalid {key}")
    if s["kind"] == 1 and not (s["run"] and s["cycle"] and s["outcome"]):
        raise ValueError("result needs run, cycle and terminal outcome")
    return value
