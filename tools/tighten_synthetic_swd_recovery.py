"""Recover failed UNCONFIRMED synthetic A while preserving confirmed B.

CPU is reset/halted in bootloader before A-only programming. No normal B
startup, direct Flash metadata edit, forced confirmation or motor command.
The existing SRAM START_TRIAL request is verified by the existing bootloader.
Requires explicit isolated-flash authorization; default performs NO operation.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import struct
import subprocess
import zlib

from firmware_transfer_iap import ROOT, image_info

CLI = r"D:\software\cubeprogrammer\bin\STM32_Programmer_CLI.exe"
OCD = r"D:\software\xpack-openocd-0.12.0-7\bin\openocd.exe"
SCRIPTS = r"D:\software\openocd-0.12.0\tcl"
SN = "0050003B3235511537333439"


def latest_meta(data):
    metas = []
    for offset in (0x7E800, 0x7F000):
        words = struct.unpack_from("<12I", data, offset)
        if words[:2] == (0x424F4F54, 3) and words[-1] == zlib.crc32(data[offset:offset + 44]):
            metas.append(words)
    if not metas:
        raise RuntimeError("No valid metadata")
    return max(metas, key=lambda w: w[5])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--permit-inactive-swd-recovery", action="store_true")
    parser.add_argument("--resume-verified-image", action="store_true",
                        help="no Flash writing: resume an exact already-read-back A image from halted bootloader")
    args = parser.parse_args()
    if not args.permit_inactive_swd_recovery:
        parser.error("No hardware operation without explicit authorization")
    evidence = ROOT / "safety_backups/tighten-synthetic-20261008"
    private = evidence / "private"
    before = (private / "before-flash.bin").read_bytes()
    failed = (private / "before-repair2-flash.bin").read_bytes()
    image_path = ROOT / "foc2_app_a/build/TightenSyntheticIsolated/foc2.bin"
    image = image_path.read_bytes()
    slot, crc = image_info(image)
    if slot != "A" or len(before) != 0x80000 or len(failed) != 0x80000:
        raise RuntimeError("Exact A image and full backups required")
    if latest_meta(before)[2:5] != (2, 0, 0) or latest_meta(failed)[2:4] != (2, 1):
        raise RuntimeError("Need original confirmed B and failed unconfirmed A")
    regions = ((0, 0x8000), (0x40000, 0x7E800), (0x7F800, 0x80000))
    for start, end in regions:
        if before[start:end] != failed[start:end]:
            raise RuntimeError("Protected region changed before recovery")
    readback = private / "repaired-startup-a.bin"
    if readback.exists() and not args.resume_verified_image:
        raise RuntimeError("Preserve prior readback; do not automatically repeat Flash writing")
    if args.resume_verified_image:
        actual = readback.read_bytes()
        if len(actual) != 0x80000 or actual[0x8000:0x8000 + len(image)] != image:
            raise RuntimeError("Already-programmed image is not exact")
        for start, end in (*regions, (0x7E800, 0x7F800)):
            if actual[start:end] != failed[start:end]:
                raise RuntimeError("Already-programmed protected region differs")
    records = {"image_sha256": hashlib.sha256(image).hexdigest(), "image_crc32": f"{crc:08X}",
               "image_size": len(image), "bootloader_modified": False, "force_confirm": False,
               "normal_b_started": False, "motion_commands": False, "steps": []}

    def cli(*args):
        p = subprocess.run([CLI, "-c", "port=SWD", "mode=HOTPLUG", "freq=1000", "sn=" + SN, *map(str, args)],
                           cwd=private, capture_output=True, text=True, errors="replace", timeout=30)
        out = p.stdout + p.stderr
        if p.returncode or "Error:" in out:
            raise RuntimeError(out)
        return out

    def registers():
        out = cli("-r32", "0xE000ED08", "4", "-r32", "0x48000814", "4", "-r32", "0x40012C44", "4",
                  "-r32", "0x40012C00", "4", "-r32", "0x40012C20", "4", "-r32", "0xE000ED28", "4",
                  "-r32", "0x4002104C", "4")
        regs = {int(a, 16): int(v, 16) for a, v in re.findall(r"(?im)^0x([0-9A-F]+)\s*:\s*([0-9A-F]{8})\s*$", out)}
        reset_gpio = (regs.get(0xE000ED08) in (0, 0x08000000, 0x08008000) and
                      regs.get(0x4002104C, 0xFFFFFFFF) & 4 == 0 and
                      regs.get(0x48000814) == 0xFFFFFFFF and regs.get(0x40012C44) == 0 and
                      regs.get(0x40012C00) == 0 and regs.get(0x40012C20) == 0)
        if (len(regs) != 7 or (not reset_gpio and regs[0x48000814] & 0x40) or regs[0x40012C44] & 0xC000 or
                regs[0x40012C00] & 1 or regs[0x40012C20] or regs[0xE000ED28] not in (0, 0x400)):
            raise RuntimeError("Unsafe/incomplete debug state; no Flash operation")
        records["steps"].append({"registers": {hex(a): hex(v) for a, v in regs.items()}})
        return regs

    def openocd(command, timeout=60):
        p = subprocess.run([OCD, "-s", SCRIPTS, "-f", "interface/stlink.cfg", "-f", "target/stm32g4x.cfg",
                            "-c", "gdb_port disabled; tcl_port disabled; telnet_port disabled; "
                            "adapter serial " + SN + "; adapter speed 1000; " + command],
                           capture_output=True, text=True, errors="replace", timeout=timeout)
        out = p.stdout + p.stderr
        records["steps"].append({"openocd_code": p.returncode, "output": out})
        print(out, flush=True)
        if p.returncode or "** Programming Failed **" in out:
            raise RuntimeError("SWD operation failed; no automatic retry")

    try:
        vector = registers()[0xE000ED08]
        if ((not args.resume_verified_image and vector != 0x08008000) or
                (args.resume_verified_image and vector not in (0, 0x08000000))):
            raise RuntimeError("Expected the failed A trial")
        # Keep halt, programming, verification and START_TRIAL in ONE debug
        # session. Detaching between reset-halt and programming can resume CPU.
        protected = []
        for index, (start, end) in enumerate((*regions, (0x7E800, 0x7F800))):
            segment = private / f"protected-startup2-{index}.bin"
            content = failed[start:end]
            if segment.exists() and segment.read_bytes() != content:
                raise RuntimeError("Preserve prior protected snapshot")
            if not segment.exists():
                segment.write_bytes(content)
            protected.append((start, segment))
        # Existing command=START_TRIAL, known-confirmed fallback=B, target=A.
        # Never issue command=CONFIRM_CURRENT or SET_CONFIRMED_SLOT.
        packet = struct.pack("<7I", 0x584F424D, 1, 2, 2, 1, len(image), crc)
        words = struct.unpack("<8I", packet + struct.pack("<I", zlib.crc32(packet)))
        commands = ["init", "halt"]
        if not args.resume_verified_image:
            commands.append("reset halt")
        commands += [
                    'set task_vtor [mrw 0xE000ED08]',
                    'if {$task_vtor != 0 && $task_vtor != 0x08000000} {error "Not halted in bootloader"}',
                    # GPIOC reads all-ones while its reset-gated bus clock is
                    # off. Enable ONLY GPIOC/TIM1 clocks to establish and read
                    # actual OFF outputs. No PWM or motor-enable operation.
                    "mmw 0x4002104C 0x4 0", "mww 0x48000818 0x00400000",
                    "mmw 0x48000800 0x1000 0x2000", "mmw 0x40021060 0x800 0",
                    "mww 0x48000818 0x00400000", "mww 0x40012C20 0",
                    "mww 0x40012C44 0", "mww 0x40012C00 0"]
        if not args.resume_verified_image:
            commands.append(f"flash write_image erase {{{image_path.as_posix()}}} 0x08008000 bin")
        commands.append(f"verify_image {{{image_path.as_posix()}}} 0x08008000 bin")
        commands += [f"verify_image {{{p.as_posix()}}} {0x08000000 + start:#x} bin"
                     for start, p in protected]
        if not args.resume_verified_image:
            commands.append(f"dump_image {{{readback.as_posix()}}} 0x08000000 0x80000")
        commands += ['if {[mrw 0x48000814] & 0x40 || [mrw 0x40012C44] & 0xC000 || [mrw 0x40012C00] & 1 || [mrw 0x40012C20]} {error "Power output not off"}',
                     'echo "OFF OUTPUT PROOF: SD=0 MOE=0 AOE=0 CCER=0 CEN=0"',
                     "mww 0x2001FFC0 0"]
        commands += [f"mww {0x2001FFC0 + index * 4:#x} {words[index]:#x}" for index in range(1, 8)]
        commands += [f"mww 0x2001FFC0 {words[0]:#x}", "reset run", "shutdown"]
        openocd("; ".join(commands))
        actual = readback.read_bytes()
        if len(actual) != 0x80000 or actual[0x8000:0x8000 + len(image)] != image:
            raise RuntimeError("A readback differs")
        for start, end in (*regions, (0x7E800, 0x7F800)):
            if actual[start:end] != failed[start:end]:
                raise RuntimeError("Protected region differs after recovery")
        print("A IMAGE EXACT; BOOTLOADER/B/KVS/PARAMETERS PRESERVED; no Flash metadata edit", flush=True)
        records["trial_requested"] = True
        print("START_TRIAL requested; existing bootloader must validate CRC and APP must pass health", flush=True)
    finally:
        (evidence / "startup-race-recovery.json").write_text(json.dumps(records, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
