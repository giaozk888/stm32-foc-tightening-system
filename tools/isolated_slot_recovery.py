"""Explicitly authorized SWD recovery of inactive A, preserving confirmed B.

Used when normal startup cannot reach its UART IAP entry. No direct metadata
write/force-confirm: request START_TRIAL in the existing CRC-protected SRAM
mailbox; the unmodified bootloader validates the image, and the APP must pass
its continuous 5 s ADC/FOC/encoder/UART/hard-off health gate.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import struct
import subprocess
import time
import zlib
import serial

ROOT = Path(__file__).resolve().parents[1]
CLI = r"D:\software\cubeprogrammer\bin\STM32_Programmer_CLI.exe"
SN = "0050003B3235511537333439"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence", required=True, type=Path)
    parser.add_argument("--permit-inactive-swd-recovery", action="store_true")
    args = parser.parse_args()
    evidence = args.evidence.resolve()
    if not args.permit_inactive_swd_recovery or not evidence.is_relative_to((ROOT / "safety_backups").resolve()):
        parser.error("Explicit authorization and workspace safety_backups required")
    evidence.mkdir(parents=True, exist_ok=True)
    image_path = ROOT / "foc2_app_a/build/RouterTransferIsolated/foc2.bin"
    image = image_path.read_bytes()
    sp, reset = struct.unpack_from("<II", image)
    assert 8 <= len(image) <= 0x38000 and 0x20000000 <= sp <= 0x2001FFC0
    assert reset & 1 and 0x08008000 <= (reset & ~1) < 0x08040000
    baseline = (evidence.parent / "20261006-router-transfer-concurrency-live/stm32-before-private.bin").read_bytes()
    assert len(baseline) == 0x80000
    records = {"image_bytes": len(image), "sha256": hashlib.sha256(image).hexdigest(),
               "swd": [], "startup": [], "motion_commands": False, "direct_metadata_write": False,
               "force_confirm": False, "pass": False}
    connection = serial.Serial(port=None, baudrate=115200, timeout=.05, write_timeout=2)
    connection.dtr = connection.rts = False
    connection.port = "COM5"

    def cli(*arguments, timeout=30):
        process = subprocess.run([CLI, "-c", "port=SWD", "mode=HOTPLUG", "freq=1000", "sn=" + SN,
                                  *map(str, arguments)], capture_output=True, text=True, timeout=timeout)
        output = process.stdout + process.stderr
        records["swd"].append({"args": list(map(str, arguments)), "code": process.returncode, "output": output})
        if process.returncode or "Error:" in output:
            raise RuntimeError(output)
        return output

    def read(address):
        for attempt in range(3):
            output = cli("-r32", hex(address), "1")
            match = re.search(rf"0x{address:08X}\s*:\s*([\dA-Fa-f]{{8}})", output, re.I)
            assert match, output
            value = int(match[1], 16)
            if value != 0xFFFFFFFF:
                return value
            # All-ones VTOR/GPIO/BDTR is not a valid peripheral snapshot.
            time.sleep(.1)
        raise RuntimeError(f"Invalid SWD snapshot at {address:x}; no write permitted")

    def drain(seconds):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            line = connection.readline().decode(errors="replace").strip()
            if line:
                records["startup"].append(line)
                print(line, flush=True)

    try:
        connection.open()
        for attempt in range(3):
            vector = read(0xE000ED08)
            assert read(0x48000814) & 0x40 == 0, "SD must remain low before recovery"
            assert read(0x40012C44) & 0x8000 == 0, "MOE must remain off"
            if vector == 0x08040000:
                break
            assert vector == 0x08008000, "Unexpected active slot"
            cli("-rst")
            print("Controlled reset to consume failed A trial; B image untouched", flush=True)
            drain(4)
        assert read(0xE000ED08) == 0x08040000, "B must be active before A write"
        before = evidence / "recovered-b-before-private.bin"
        cli("-u", "0x08000000", "0x80000", before)
        current = before.read_bytes()
        for start, end in ((0, 0x8000), (0x40000, 0x78000), (0x78000, 0x7E800), (0x7F800, 0x80000)):
            assert current[start:end] == baseline[start:end], f"Protected region differs {start:x}"
        metas = []
        for offset in (0x7E800, 0x7F000):
            words = struct.unpack_from("<12I", current, offset)
            assert words[0] == 0x424F4F54 and words[1] == 3
            assert words[-1] == zlib.crc32(current[offset:offset + 44])
            metas.append(words)
        latest = max(metas, key=lambda words: words[5])
        assert latest[2:5] == (2, 0, 0), "Expected confirmed B, no pending trial"
        print("SAFE B ACTIVE; bootloader/B/KVS/parameters preserved; writing inactive A only", flush=True)
        if current[0x8000:0x8000 + len(image)] == image:
            print("Inactive A already matches the requested image; no second flash write", flush=True)
        else:
            # CubeProgrammer's HOTPLUG loader timed out on this board. Use a
            # halted OpenOCD flash loader instead, with an explicit A-only range.
            commands = (f"log_output {{{(evidence / 'openocd-a-program.log').as_posix()}}}; "
                        f"adapter serial {SN}; adapter speed 1000; init; halt; "
                        "mww 0x48000818 0x00400000; mww 0x40012C20 0; "
                        "mww 0x40012C44 0x02002055; mww 0x40012C00 0x20; "
                        f"flash write_image erase {{{image_path.as_posix()}}} 0x08008000 bin; "
                        f"verify_image {{{image_path.as_posix()}}} 0x08008000 bin; shutdown")
            programmed = subprocess.run([r"D:\software\xpack-openocd-0.12.0-7\bin\openocd.exe",
                "-s", r"D:\software\openocd-0.12.0\tcl", "-f", "interface/stlink.cfg",
                "-f", "target/stm32g4x.cfg", "-c", commands], capture_output=True, text=True, timeout=60)
            records["openocd_program"] = {"code": programmed.returncode,
                "output": programmed.stdout + programmed.stderr}
            assert programmed.returncode == 0, records["openocd_program"]
        assert read(0xE000ED08) == 0x08040000
        programmed = evidence / "a-programmed-private.bin"
        cli("-u", "0x08000000", "0x80000", programmed)
        actual = programmed.read_bytes()
        assert actual[0x8000:0x8000 + len(image)] == image
        assert actual[0x40000:0x78000] == baseline[0x40000:0x78000]
        # Requester=B, command=START_TRIAL, target=A. Write magic last.
        packet = struct.pack("<7I", 0x584F424D, 1, 2, 2, 1, len(image), zlib.crc32(image))
        request = struct.unpack("<8I", packet + struct.pack("<I", zlib.crc32(packet)))
        cli("-w32", "0x2001FFC0", "0", "-w32", "0x2001FFC4", *map(hex, request[1:]),
            "-w32", "0x2001FFC0", hex(request[0]), "-rst")
        print("Existing bootloader START_TRIAL requested; awaiting normal health confirmation", flush=True)
        deadline = time.monotonic() + 70
        seq = 48500
        confirmed = False
        while time.monotonic() < deadline:
            seq += 1
            connection.write(f"{seq} FW STATUS\r\n".encode())
            response_deadline = time.monotonic() + 1
            while time.monotonic() < response_deadline:
                line = connection.readline().decode(errors="replace").strip()
                if not line:
                    continue
                records["startup"].append(line)
                print(line, flush=True)
                if line.startswith(f"{seq} OK FW") and "CURRENT=A" in line and "CONFIRMED=A" in line and "PENDING=-" in line:
                    confirmed = True
                    records["confirmed"] = line
                    break
            if confirmed:
                break
        assert confirmed, "A did not pass its health gate; no force-confirm attempted"
        connection.write(b"48600 ANALOG SAFE\r\n")
        drain(2)
        assert any(line.startswith("48600 OK ANALOG SAFE LATCHED=1 SD=0 MOE=0 FOC=0") for line in records["startup"])
        records["pass"] = True
        print("INACTIVE A SWD RECOVERY + BOOTLOADER TRIAL/HEALTH CONFIRM PASS", flush=True)
    finally:
        connection.close()
        (evidence / "recovery.json").write_text(json.dumps(records, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
