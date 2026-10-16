"""Read-only final audit of the temporary output-locked diagnostic firmware.

No flashing, reset, halt, current sampling, fault clearing or motor commands.
--saved-flash reads protected local evidence, not live Flash contents.
"""
import argparse
import hashlib
import json
import re
import subprocess
import time
import zlib

from zero_retest_deploy import (
    CLI, SN, ROOT, OUTPUT, PINNED, DiagnosticUart, latest_meta,
    require_confirmed, require_service,
)


def audit_saved_flash():
    private = OUTPUT / "private"
    before = (private / "before-A.bin").read_bytes()
    after = (private / "final-B.bin").read_bytes()
    if len(before) != 0x80000 or len(after) != 0x80000:
        raise RuntimeError("Complete 512 KiB captures required")
    protected = {}
    for name, start, end in (
        ("bootloader", 0, 0x8000),
        ("KVS_reserved", 0x78000, 0x7E800),
        ("parameters", 0x7F800, 0x80000),
    ):
        if before[start:end] != after[start:end]:
            raise RuntimeError("Protected region changed: " + name)
        protected[name] = "unchanged"
    meta = latest_meta(after)
    if meta[2:6] != (2, 0, 0, 356):
        raise RuntimeError("Unexpected final B confirmation metadata")
    images = {}
    for slot, start, index in (("A", 0x8000, 6), ("B", 0x40000, 8)):
        image = (ROOT / f"foc2_app_{slot.lower()}/build/ZeroRetestLocked20261008/foc2.bin").read_bytes()
        sha = hashlib.sha256(image).hexdigest()
        crc = zlib.crc32(image)
        if sha != PINNED[slot] or after[start:start + len(image)] != image:
            raise RuntimeError("Exact pinned diagnostic image required: " + slot)
        if meta[index:index + 2] != (len(image), crc):
            raise RuntimeError("Image metadata differs: " + slot)
        images[slot] = {"bytes": len(image), "sha256": sha, "crc32": f"{crc:08X}"}
    return {"protected": protected, "images": images,
            "confirmed": "B", "pending": None, "attempts": 0, "generation": 356}


def observe_outputs():
    import serial
    port = serial.Serial(port=None, baudrate=115200, timeout=.02, write_timeout=1)
    port.dtr = port.rts = False
    port.port = "COM5"
    uart = DiagnosticUart(port)
    rows = []
    try:
        port.open()
        require_confirmed(uart.query("FW STATUS", 3), "B")
        start = time.monotonic()
        for _ in range(30):
            line = uart.query("ZERO STATUS")
            row = require_service(line)
            if any(row.get(k) != v for k, v in
                   (("ADC_READY", "1"), ("STATE", "0"), ("N", "0"), ("ADC", "0"))):
                raise RuntimeError("Expected initialized but unsampled idle service")
            rows.append(line)
            time.sleep(.3)
        elapsed = time.monotonic() - start
        fw = require_confirmed(uart.query("FW STATUS"), "B")
        if fw.get("GEN") != "356":
            raise RuntimeError("Boot metadata changed during read-only observation")
        analog = uart.query("ANALOG VOLT")
    finally:
        port.close()
    addresses = (0xE000ED08, 0x48000814, 0x40012C44, 0x40012C00, 0x40012C20, 0xE000ED28)
    command = [CLI, "-c", "port=SWD", "mode=HOTPLUG", "freq=1000", "sn=" + SN]
    for address in addresses:
        command.extend(("-r32", hex(address), "4"))
    proc = subprocess.run(command, capture_output=True, text=True, errors="replace", timeout=30)
    output = proc.stdout + proc.stderr
    regs = {int(a, 16): int(v, 16) for a, v in
            re.findall(r"(?im)^0x([0-9A-F]+)\s*:\s*([0-9A-F]{8})\s*$", output)}
    if proc.returncode or set(regs) != set(addresses):
        raise RuntimeError("Read-only SWD register capture failed")
    if (regs[0xE000ED08] != 0x08040000 or regs[0x48000814] & 0x40 or
            regs[0x40012C44] & 0xC000 or regs[0x40012C00] & 1 or
            regs[0x40012C20] or regs[0xE000ED28]):
        raise RuntimeError("Independent hardware output/fault check failed")
    return {"polls": len(rows), "seconds": round(elapsed, 3), "fw": fw,
            "zero_status": rows, "analog": analog,
            "registers": {f"0x{a:08X}": f"{v:08X}" for a, v in regs.items()},
            "note": "ADC initialization is not zero qualification; no injected samples or FOC"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--saved-flash", action="store_true")
    parser.add_argument("--observe", action="store_true")
    args = parser.parse_args()
    if not (args.saved_flash or args.observe):
        parser.error("Choose an explicit read-only audit")
    result = {"pass": False, "zero_qualified": False, "motion_commands": False,
              "sampling_commands": False, "reset": False, "flash_write": False}
    target = OUTPUT / f"final-audit-{time.time_ns()}.json"
    try:
        if args.saved_flash:
            result["saved_flash"] = audit_saved_flash()
        if args.observe:
            result["observation"] = observe_outputs()
        result["pass"] = True
    except Exception as error:
        result["failure"] = str(error)
        raise
    finally:
        target.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print("Evidence: " + str(target))
    print("READ-ONLY LOCK AUDIT PASS; zero/FOC/hardware alarm NOT qualified")


if __name__ == "__main__":
    main()
