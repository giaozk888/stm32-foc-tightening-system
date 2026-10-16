"""Deploy ONLY the pinned hard-off diagnostic APP to its INACTIVE slot.

Explicit --allow-deploy requires drive 12 V physically OFF. This never sends
motor/clear/force-confirm commands or writes bootloader/Flash metadata. The
existing bootloader receives START_TRIAL in SRAM; the APP confirms only its
locked diagnostic service after 5 s of fresh local-console health evidence.
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

from firmware_transfer_iap import ROOT, Uart, fields, image_info
from tighten_synthetic_swd_recovery import latest_meta, CLI, OCD, SCRIPTS, SN

PINNED = {
    "A": "8f4d129a1cf86fd87b747544c6796d82360b4b87178782c1ea8ba3925f63b0bf",
    "B": "8bec1d3b7eaabeac712fd97e812e3a51727eb4c48a086cd62ad1824452505fc1",
}
OUTPUT = ROOT / "safety_backups/zero-retest-locked-20261008"

def require_service(line):
    row = fields(line)
    for key, value in (("PROFILE", "LOCKED_DIAGNOSTIC"), ("LOCK", "1"),
                       ("SD", "0"), ("MOE", "0"), ("CCER", "0"), ("CEN", "0"),
                       ("FOC", "0"), ("MOTOR_READY", "0"), ("IF", "0"), ("ACTIVE", "0")):
        if row.get(key) != value:
            raise RuntimeError("Diagnostic output proof failed: " + line)
    return row

def require_confirmed(line, slot):
    row = fields(line)
    if any(row.get(k) != v for k, v in (("CURRENT", slot), ("CONFIRMED", slot),
                                       ("PENDING", "-"), ("ATTEMPTS", "0"), ("ACTIVE", "0"))):
        raise RuntimeError("Expected a confirmed idle " + slot + ": " + line)
    return row

def compare_flash(before, actual, image, slot, staged=False):
    if len(before) != 0x80000 or len(actual) != 0x80000 or image_info(image)[0] != slot:
        raise RuntimeError("Complete captures and correct slot image required")
    target, other = (0x8000, 0x40000) if slot == "A" else (0x40000, 0x8000)
    old, new = latest_meta(before), latest_meta(actual)
    requester = 2 if slot == "A" else 1
    if old[2:5] != (requester, 0, 0):
        raise RuntimeError("Baseline has a pending/incorrect slot")
    if actual[target:target + len(image)] != image:
        raise RuntimeError("Inactive APP differs from exact image")
    protected = (("bootloader", 0, 0x8000), ("fallback", other, other + 0x38000),
                 ("KVS_reserved", 0x78000, 0x7E800), ("parameters", 0x7F800, 0x80000))
    for name, start, end in protected:
        if before[start:end] != actual[start:end]:
            raise RuntimeError("Protected region changed: " + name)
    other_index = 8 if slot == "A" else 6
    if old[other_index:other_index + 2] != new[other_index:other_index + 2]:
        raise RuntimeError("Fallback image metadata changed")
    if staged:
        if before[0x7E800:0x7F800] != actual[0x7E800:0x7F800]:
            raise RuntimeError("Staging changed Flash metadata")
    else:
        slot_id = 1 if slot == "A" else 2
        index = 6 if slot == "A" else 8
        if new[2:5] != (slot_id, 0, 0) or new[index:index + 2] != (len(image), zlib.crc32(image)):
            raise RuntimeError("Diagnostic APP not normally confirmed with exact size/CRC")
    return {"all_protected_regions_unchanged": True, "confirmed": new[2],
            "generation": new[5], "staged": staged}

class DiagnosticUart(Uart):
    def __init__(self, port):
        super().__init__(port)
        self.request = 81000
        self.lines = []

    def dispatch(self, line):
        if line:
            self.lines.append(line)
            if "ZERO RETEST:" in line or "ZERO SERVICE HEALTH" in line:
                print(line, flush=True)
            if "HardFault" in line or "CREATE FAILED" in line:
                raise RuntimeError("Diagnostic startup fault: " + line)

    def query(self, command, timeout=1.0):
        if command not in ("FW STATUS", "ANALOG SAFE STATUS", "STATUS", "ZERO STATUS", "ANALOG VOLT"):
            raise ValueError("Read-only diagnostic queries only")
        self.request += 1
        self.port.write(f"{self.request} {command}\r\n".encode("ascii"))
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            line = self.read_line(min(.05, deadline - time.monotonic()))
            if line is None:
                continue
            self.dispatch(line)
            if line.startswith(f"{self.request} "):
                if not line.startswith(f"{self.request} OK "):
                    raise RuntimeError(line)
                return line
        raise TimeoutError("No diagnostic ACK: " + command)

def observe(uart, slot):
    deadline = time.monotonic() + 35
    seen = False
    while time.monotonic() < deadline:
        try:
            row = require_service(uart.query("ZERO STATUS", .5))
            fw = uart.query("FW STATUS", .5)
        except TimeoutError:
            continue
        except RuntimeError as error:
            # Unknown ZERO command means the original fallback, never retry/reset it.
            raise RuntimeError("Target diagnostic service unavailable: " + str(error)) from error
        if fields(fw).get("CURRENT") != slot:
            if seen:
                raise RuntimeError("Rolled back instead of confirming diagnostic APP")
            continue
        seen = True
        if fields(fw).get("CONFIRMED") == slot and fields(fw).get("PENDING") == "-":
            require_confirmed(fw, slot)
            require_service(uart.query("ZERO STATUS"))
            print(f"LOCKED SERVICE PASS: {slot}, normally confirmed; zero/FOC NOT tested", flush=True)
            return
        until = min(deadline, time.monotonic() + .3)
        while time.monotonic() < until:
            uart.poll(.02)
    raise TimeoutError("Diagnostic service did not pass its own health gate; no forced confirmation")

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--slot", choices=("A", "B"), required=True)
    parser.add_argument("--allow-deploy", action="store_true")
    parser.add_argument("--drive-12v-off", action="store_true")
    parser.add_argument("--recover-failed-stage", action="store_true",
                        help="A-only controlled reset-halt recovery after a preserved failed SWD stage")
    args = parser.parse_args()
    import serial
    port = serial.Serial(port=None, baudrate=115200, timeout=.02, write_timeout=1)
    port.dtr = port.rts = False
    port.port = "COM5"
    uart = DiagnosticUart(port)
    records = {"slot": args.slot, "pass": False, "motion_commands": False,
               "direct_metadata_write": False, "force_confirm": False,
               "zero_qualified": False, "operations": []}
    OUTPUT.mkdir(parents=True, exist_ok=True)
    target = OUTPUT / f"deploy-{args.slot}-{time.time_ns()}.json"
    private = OUTPUT / "private"
    private.mkdir(exist_ok=True)

    def cli(*arguments):
        p = subprocess.run([CLI, "-c", "port=SWD", "mode=HOTPLUG", "freq=1000", "sn=" + SN,
                            *map(str, arguments)], capture_output=True, text=True, errors="replace", timeout=30)
        out = p.stdout + p.stderr
        records["operations"].append({"tool": "CLI", "args": list(map(str, arguments)), "code": p.returncode, "output": out})
        if p.returncode or "Error:" in out:
            raise RuntimeError("Read-only SWD failed: " + out)
        return out

    try:
        port.open()
        if args.recover_failed_stage and (args.slot != "A" or not args.allow_deploy):
            raise RuntimeError("Failed-stage recovery is explicit A-only")
        if not args.recover_failed_stage:
            fw = uart.query("FW STATUS", 3)
            safe = fields(uart.query("ANALOG SAFE STATUS", 3))
            if any(safe.get(k) != v for k, v in (("LATCHED", "1"), ("SD", "0"), ("MOE", "0"), ("FOC", "0"))):
                raise RuntimeError("Current output-off latch absent")
        if not args.allow_deploy:
            print("READ-ONLY: " + fw)
            return
        if not args.drive_12v_off:
            raise RuntimeError("Require explicit drive 12 V OFF; no powered migration")
        requester = "B" if args.slot == "A" else "A"
        if not args.recover_failed_stage:
            require_confirmed(fw, requester)
        if args.slot == "B":
            require_service(uart.query("ZERO STATUS"))
        image_path = ROOT / f"foc2_app_{args.slot.lower()}/build/ZeroRetestLocked20261008/foc2.bin"
        image = image_path.read_bytes()
        if image_info(image)[0] != args.slot or hashlib.sha256(image).hexdigest() != PINNED[args.slot]:
            raise RuntimeError("Only pinned offline-built hard-off diagnostic image admitted")
        address = 0x08008000 if args.slot == "A" else 0x08040000
        before_path = private / f"before-{args.slot}.bin"
        staged_path = private / f"staged-{args.slot}.bin"
        final_path = private / f"final-{args.slot}.bin"
        if any(p.exists() for p in (staged_path, final_path)) or (before_path.exists() and not args.recover_failed_stage):
            raise RuntimeError("Preserve previous evidence; never automatically repeat deployment")
        if not args.recover_failed_stage:
            cli("-u", "0x08000000", "0x80000", before_path)
        before = before_path.read_bytes()
        if args.recover_failed_stage:
            failed = (private / "failed-stage-A.bin").read_bytes()
            if len(failed) != 0x80000 or latest_meta(failed) != latest_meta(before):
                raise RuntimeError("Failed-stage metadata differs; no recovery")
            for start, end in ((0, 0x8000), (0x40000, 0x80000)):
                if before[start:end] != failed[start:end]:
                    raise RuntimeError("Failed-stage changed bootloader/B/data; no recovery")
            records["controlled_recovery"] = True
        meta = latest_meta(before)
        if meta[2:5] != (2 if requester == "B" else 1, 0, 0):
            raise RuntimeError("Flash boot metadata contradicts UART")
        regout = cli("-r32", "0xE000ED08", "4", "-r32", "0x48000814", "4",
                     "-r32", "0x40012C44", "4", "-r32", "0x40012C00", "4", "-r32", "0x40012C20", "4")
        regs = dict((int(a, 16), int(v, 16)) for a, v in re.findall(r"(?im)^0x([0-9A-F]+)\s*:\s*([0-9A-F]{8})\s*$", regout))
        if (len(regs) != 5 or regs[0xE000ED08] != (0x08040000 if requester == "B" else 0x08008000) or
            regs[0x48000814] & 0x40 or regs[0x40012C44] & 0xC000 or regs[0x40012C00] & 1 or regs[0x40012C20]):
            raise RuntimeError("Read-only hardware proof unsafe/incomplete")
        protected = ((0, 0x8000), (0x40000, 0x78000) if args.slot == "A" else (0x8000, 0x40000),
                     (0x78000, 0x80000))
        segments = []
        for i, (start, end) in enumerate(protected):
            segment = private / f"protected-{args.slot}-{i}.bin"
            segment.write_bytes(before[start:end])
            segments.append((start, segment))
        # Old B is never resumed after A programming. No reset until the
        # exact inactive image and every protected region have been verified.
        packet = struct.pack("<7I", 0x584F424D, 1, 2, 2 if requester == "B" else 1,
                             1 if args.slot == "A" else 2, len(image), zlib.crc32(image))
        words = struct.unpack("<8I", packet + struct.pack("<I", zlib.crc32(packet)))
        commands = ["init", "halt", "reset halt",
                    'if {[mrw 0xE000ED08] != 0 && [mrw 0xE000ED08] != 0x08000000} {error "Not halted in bootloader"}',
                    "mmw 0x4002104C 0x4 0", "mww 0x48000818 0x00400000",
                    "mmw 0x48000800 0x1000 0x2000", "mmw 0x40021060 0x800 0",
                    "mww 0x48000818 0x00400000", "mww 0x40012C20 0",
                    "mmw 0x40012C44 0 0xC000", "mmw 0x40012C00 0 1",
                    f"flash write_image erase {{{image_path.as_posix()}}} {address:#x} bin",
                    f"verify_image {{{image_path.as_posix()}}} {address:#x} bin"]
        commands += [f"verify_image {{{path.as_posix()}}} {0x08000000 + start:#x} bin" for start, path in segments]
        commands += [f"dump_image {{{staged_path.as_posix()}}} 0x08000000 0x80000",
                     'if {[mrw 0x48000814] & 0x40 || [mrw 0x40012C44] & 0xC000 || [mrw 0x40012C00] & 1 || [mrw 0x40012C20]} {error "Output off proof failed"}',
                     "mww 0x2001FFC0 0"]
        commands += [f"mww {0x2001FFC0 + i * 4:#x} {words[i]:#x}" for i in range(1, 8)]
        commands += [f"mww 0x2001FFC0 {words[0]:#x}", "reset run", "shutdown"]
        p = subprocess.run([OCD, "-s", SCRIPTS, "-f", "interface/stlink.cfg", "-f", "target/stm32g4x.cfg",
                            "-c", "gdb_port disabled; tcl_port disabled; telnet_port disabled; adapter serial " + SN +
                            "; adapter speed 1000; " + "; ".join(commands)], capture_output=True, text=True, errors="replace", timeout=60)
        out = p.stdout + p.stderr
        records["operations"].append({"tool": "OpenOCD", "code": p.returncode, "output": out})
        print(out, flush=True)
        if p.returncode or "** Programming Failed **" in out:
            raise RuntimeError("Programming did not complete; no retry, no blind reset")
        records["staged_flash"] = compare_flash(before, staged_path.read_bytes(), image, args.slot, staged=True)
        observe(uart, args.slot)
        # Another 3 s of stopped/off evidence after normal diagnostic confirmation.
        for _ in range(10):
            require_service(uart.query("ZERO STATUS"))
            time.sleep(.3)
        records["final_fw"] = require_confirmed(uart.query("FW STATUS"), args.slot)
        records["final_zero"] = require_service(uart.query("ZERO STATUS"))
        records["analog"] = fields(uart.query("ANALOG VOLT"))
        cli("-u", "0x08000000", "0x80000", final_path)
        records["final_flash"] = compare_flash(before, final_path.read_bytes(), image, args.slot)
        records["pass"] = True
    except BaseException as error:
        records["failure"] = str(error)
        raise
    finally:
        records["uart"] = uart.lines
        port.close()
        target.write_text(json.dumps(records, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print("Evidence: " + str(target), flush=True)

if __name__ == "__main__":
    main()
