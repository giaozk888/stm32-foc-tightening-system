"""Return this isolated FD experiment to its untouched original confirmed A.

Only a CRC-protected START_TRIAL SRAM request and reset are written over SWD;
the existing bootloader verifies A and the APP must normally pass its health
gate. No APP/bootloader Flash write, metadata write, or force-confirm command.
"""
import argparse
import asyncio
import hashlib
import json
from pathlib import Path
import re
import struct
import subprocess
import sys
import time
import zlib

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.router_transfer_concurrency_live import Console, ALLOWED

CLI = r"D:\software\cubeprogrammer\bin\STM32_Programmer_CLI.exe"
SN = "0050003B3235511537333439"


def latest_meta(data):
    records = []
    for offset in (0x7e800, 0x7f000):
        words = struct.unpack_from("<12I", data, offset)
        if words[:2] == (0x424f4f54, 3) and words[-1] == zlib.crc32(data[offset:offset+44]):
            records.append(words)
    if not records:
        raise RuntimeError("No valid CRC-protected metadata")
    return max(records, key=lambda words: words[5])


async def restore(args, evidence, result):
    baseline_path = args.baseline.resolve()
    if not baseline_path.is_relative_to((ROOT / "safety_backups").resolve()):
        raise RuntimeError("Baseline must remain within workspace safety_backups")
    baseline = baseline_path.read_bytes()
    if len(baseline) != 0x80000:
        raise RuntimeError("Invalid full Flash baseline")
    original = latest_meta(baseline)
    if original[2:5] != (1, 0, 0):
        raise RuntimeError("This experiment requires original confirmed A")
    size, crc = original[6:8]
    if not 8 <= size <= 0x38000 or zlib.crc32(baseline[0x8000:0x8000+size]) != crc:
        raise RuntimeError("Original A size/CRC invalid")

    def cli(*parameters):
        process = subprocess.run([CLI, "-c", "port=SWD", "mode=HOTPLUG", "freq=1000",
                                  "sn=" + SN, *map(str, parameters)], capture_output=True,
                                  text=True, timeout=30)
        output = process.stdout + process.stderr
        result["swd"].append({"args": list(map(str, parameters)), "code": process.returncode,
                              "output": output})
        if process.returncode or "Error:" in output:
            raise RuntimeError(output)
        return output

    def read(address):
        output = cli("-r32", hex(address), "4")
        match = re.search(rf"0x{address:08X}\s*:\s*([0-9A-Fa-f]{{8}})", output, re.I)
        if not match or int(match[1], 16) == 0xffffffff:
            raise RuntimeError("Invalid SWD read; no write allowed")
        return int(match[1], 16)

    def capture(name):
        path = evidence / name
        if path.exists():
            raise RuntimeError("Do not overwrite a previous full Flash capture")
        cli("-u", "0x08000000", "0x80000", path)
        data = path.read_bytes()
        if len(data) != len(baseline):
            raise RuntimeError("Incomplete full Flash capture")
        for start, end in ((0, 0x8000), (0x8000, 0x40000), (0x78000, 0x7e800), (0x7f800, 0x80000)):
            if data[start:end] != baseline[start:end]:
                raise RuntimeError(f"Protected region changed: {start:x}..{end:x}")
        result[name + "_protected_regions_equal"] = True
        return data

    console = Console(args.port, evidence)
    try:
        fw = (await console.request("FW STATUS"))[0]
        safe = (await console.request("ANALOG SAFE STATUS"))[0]
        if "SD=0 MOE=0 FOC=0" not in safe:
            raise RuntimeError("Output not safely off; no reset/write permitted")
        if read(0x48000814) & 0x40 or read(0x40012c44) & 0x8000:
            raise RuntimeError("Register safety checks failed")
        data = capture("before-return-private.bin")
        current = latest_meta(data)
        if "CURRENT=A" in fw and "CONFIRMED=A" in fw and "PENDING=-" in fw:
            if current[2:5] != (1, 0, 0) or read(0xe000ed08) != 0x08008000:
                raise RuntimeError("Unexpected original-A state")
            result["already_original_a"] = True
        else:
            if not all(item in fw for item in ("CURRENT=B", "CONFIRMED=B", "PENDING=-", "ACTIVE=0")):
                raise RuntimeError("Only confirmed B can request an A trial; no force-confirm")
            if current[2:5] != (2, 0, 0) or read(0xe000ed08) != 0x08040000:
                raise RuntimeError("Unexpected B metadata/vector")
            packet = struct.pack("<7I", 0x584f424d, 1, 2, 2, 1, size, crc)
            words = struct.unpack("<8I", packet + struct.pack("<I", zlib.crc32(packet)))
            cli("-w32", "0x2001ffc0", "0", "-w32", "0x2001ffc4", *map(hex, words[1:]),
                "-w32", "0x2001ffc0", hex(words[0]), "-rst")
            result["start_trial_requested"] = True
            print("Original A untouched; normal bootloader START_TRIAL requested", flush=True)
            deadline = time.monotonic() + 70
            while time.monotonic() < deadline:
                try:
                    fw = (await console.request("FW STATUS"))[0]
                except TimeoutError:
                    continue
                if all(item in fw for item in ("CURRENT=A", "CONFIRMED=A", "PENDING=-", "ATTEMPTS=0")):
                    break
                await asyncio.sleep(.2)
            else:
                raise RuntimeError("Original A did not normally confirm; no force-confirm")
        ALLOWED.add("ANALOG SAFE")  # Fixed power-OFF latch, never an enable command.
        safe = (await console.request("ANALOG SAFE"))[0]
        if "LATCHED=1 SD=0 MOE=0 FOC=0" not in safe:
            raise RuntimeError("Safe latch not proven")
        await console.request("BENCH STATUS")
        final = capture("final-private.bin")
        if latest_meta(final)[2:5] != (1, 0, 0) or read(0xe000ed08) != 0x08008000:
            raise RuntimeError("Final confirmed-A state not proven")
        if read(0xe000ed28) != 0:
            raise RuntimeError("CFSR is nonzero after restore")
        result.update({"pass": True, "confirmed": fw, "safe": safe,
                       "original_a_size": size, "original_a_crc32": f"{crc:08X}",
                       "original_a_sha256": hashlib.sha256(baseline[0x8000:0x8000+size]).hexdigest(),
                       "final_metadata": list(latest_meta(final)),
                       "b_slot_changed": final[0x40000:0x78000] != baseline[0x40000:0x78000]})
        print("ORIGINAL A RESTORE PASS: normal health confirmation; protected regions equal", flush=True)
    finally:
        console.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence", required=True, type=Path)
    parser.add_argument("--port", default="COM5")
    parser.add_argument("--baseline", type=Path,
        default=ROOT / "safety_backups/20261006-canfd-wire/stm32-before-private.bin")
    parser.add_argument("--permit-return-to-original", action="store_true")
    args = parser.parse_args()
    evidence = args.evidence.resolve()
    if not args.permit_return_to_original or not evidence.is_relative_to((ROOT / "safety_backups").resolve()):
        parser.error("Explicit isolated return/reset permission and workspace evidence required")
    if (evidence / "restore.json").exists():
        parser.error("Use a fresh evidence directory")
    evidence.mkdir(parents=True, exist_ok=True)
    result = {"pass": False, "swd": [], "direct_metadata_write": False,
              "app_flash_write": False, "force_confirm": False, "motor_commands": False}
    try:
        asyncio.run(restore(args, evidence, result))
    finally:
        (evidence / "restore.json").write_text(json.dumps(result, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
