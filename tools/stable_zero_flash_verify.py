"""Offline Flash comparison only. Does not open serial or debug hardware."""
import argparse
import hashlib
import json
import zlib
from pathlib import Path
from firmware_transfer_iap import image_info
from tighten_synthetic_swd_recovery import latest_meta

def verify(before, actual, image, staged=False, rolled_back=False):
    if len(before) != 0x80000 or len(actual) != 0x80000 or image_info(image)[0] != "A":
        raise RuntimeError("Need complete 512KiB captures and APP A image")
    old, new = latest_meta(before), latest_meta(actual)
    if old[2:5] != (2, 0, 0):
        raise RuntimeError("Baseline must prove confirmed B with no pending trial")
    protected = {}
    for name, start, end in (("bootloader", 0, 0x8000), ("B", 0x40000, 0x78000),
        ("KVS_reserved", 0x78000, 0x7E800), ("parameters", 0x7F800, 0x80000)):
        if before[start:end] != actual[start:end]:
            raise RuntimeError("Protected region changed: " + name)
        protected[name] = True
    if actual[0x8000:0x8000+len(image)] != image:
        raise RuntimeError("APP A readback differs from the exact image")
    if staged and rolled_back:
        raise ValueError("Choose only one verification mode")
    if staged:
        if before[0x7E800:0x7F800] != actual[0x7E800:0x7F800]:
            raise RuntimeError("Staging unexpectedly changed Flash boot metadata")
    elif rolled_back:
        if new[2:5] != (2, 0, 0) or new[6:8] != (0, 0):
            raise RuntimeError("Expected confirmed B and retired failed A trial")
    elif new[2:5] != (1, 0, 0) or new[6:8] != (len(image), zlib.crc32(image)):
        raise RuntimeError("APP A is not confirmed with its correct image CRC/size")
    if new[8:10] != old[8:10]:
        raise RuntimeError("Fallback B metadata changed")
    return {"protected_regions_unchanged": protected, "staged_only": staged, "rolled_back": rolled_back,
        "image_size": len(image), "image_crc32": f"{zlib.crc32(image):08X}",
        "image_sha256": hashlib.sha256(image).hexdigest(),
        "confirmed_slot": new[2], "pending": new[3], "attempts": new[4],
        "generation": new[5], "fallback_b_bytes": new[8], "fallback_b_crc32": f"{new[9]:08X}"}

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--before", required=True, type=Path)
    parser.add_argument("--actual", required=True, type=Path)
    parser.add_argument("--image", required=True, type=Path)
    parser.add_argument("--staged", action="store_true")
    parser.add_argument("--rolled-back", action="store_true")
    args = parser.parse_args()
    result = verify(args.before.read_bytes(), args.actual.read_bytes(), args.image.read_bytes(), args.staged, args.rolled_back)
    print(json.dumps(result, indent=2))

if __name__ == "__main__":
    main()
