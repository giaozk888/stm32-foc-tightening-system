"""Stage the exact 4 A B image only; never commit, reset, sample, or run it.

Requires the exact confirmed locked injected-zero A and known raw B baseline.
All SWD operations are read-only HOTPLUG. Preserve A, bootloader, metadata,
KVS and parameters, with full private before/after backups.
"""
import argparse
import hashlib
import json
import re
import subprocess
import time

from firmware_transfer_iap import ROOT, DEFAULT_CLIENT, fields, image_info, stage
from zero_retest_deploy import CLI, SN, require_confirmed, require_service, compare_flash
from zero_span100_acceptance import ADDRESSES, AcceptanceUart, require_registers
from zero_async_clock_acceptance import locked_baseline
from zero_injected_control_acceptance import (
    PINNED as LOCKED, PATH_ADDRESSES, require_injected_registers,
)

TARGET_SHA = "1e9010e5e82d9b7e803cf0b06def2f59e4bfe0625984211bf5e1a36bdaeb6eb3"
IMAGE = ROOT / "foc2_app_b/build/PhaseCurrentTrip4A20261012/foc2.bin"
OUTPUT = ROOT / "safety_backups/phase-current-4a-stage-20261012"


def target_image():
    image = IMAGE.read_bytes()
    if (image_info(image)[0] != "B" or len(image) != 199168 or
            hashlib.sha256(image).hexdigest() != TARGET_SHA or
            b"Phase trip      : 4.0A; powered validation pending" not in image):
        raise RuntimeError("Only the exact offline-verified 4 A B image is admitted")
    return IMAGE, image


def baseline(data):
    result = locked_baseline(data, known={s: frozenset((LOCKED[s],)) for s in "AB"})
    if result["current"] != "A":
        raise RuntimeError("Only exact confirmed locked A may stage inactive B")
    return result


class StageOnlyUart(AcceptanceUart):
    def command(self, text, timeout=5):
        if not re.fullmatch(
                r"FW (STATUS|BEGIN [0-9]+ [0-9A-F]{8})|ANALOG SAFE STATUS|"
                r"XFER ENGINE (STATUS|CLOSE|[0-9A-F]{2,192})", text):
            raise ValueError("Stage-only command rejected; no activation/reset/motion")
        return super().command(text, timeout)

    def query(self, text, timeout=1):
        if text not in ("FW STATUS", "ZERO STATUS", "ANALOG SAFE STATUS"):
            raise ValueError("Stage-only read query rejected")
        return super().query(text, timeout)


def require_staged(line, generation, image):
    row = fields(line)
    _, crc = image_info(image)
    expected = {"CURRENT": "A", "CONFIRMED": "A", "PENDING": "-",
                "ATTEMPTS": "0", "GEN": str(generation), "ACTIVE": "1",
                "TARGET": "B", "RX": str(len(image)), "SIZE": str(len(image)),
                "EXPECT": f"0x{crc:08X}"}
    if any(row.get(k, "").upper() != v.upper() for k, v in expected.items()):
        raise RuntimeError("Staged status mismatch; never activate or reset")
    return row


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--allow-stage", action="store_true")
    parser.add_argument("--drive-12v-off", action="store_true")
    args = parser.parse_args()
    if not args.allow_stage or not args.drive_12v_off:
        parser.error("Explicit staging permission and physical drive 12 V OFF required")
    path, image = target_image()
    if not DEFAULT_CLIENT.is_file():
        parser.error("Official native transfer client missing")
    OUTPUT.mkdir(parents=True, exist_ok=True)
    private = OUTPUT / "private"
    private.mkdir(exist_ok=True)
    subprocess.run(["icacls", str(private), "/inheritance:r", "/grant:r",
                    "*S-1-5-18:(OI)(CI)F", "*S-1-5-32-544:(OI)(CI)F"],
                   check=True, capture_output=True, text=True)
    run_id = str(time.time_ns())
    evidence = OUTPUT / f"stage-{run_id}.json"
    record = {"pass": False, "stage_only": True, "image_sha256": TARGET_SHA,
              "image_size": len(image), "target_slot": "B", "steps": [],
              "physical_drive_off_user_confirmed": True, "fw_end": False,
              "reset": False, "activation": False, "motion_commands": False,
              "sampling_commands": False, "direct_metadata_write": False,
              "zero_qualified": False, "motor_qualified": False}
    port = uart = None

    def cli(*arguments):
        # Explicitly prevent passing any reset, write, erase, or halt option.
        tokens = list(map(str, arguments))
        if not tokens or tokens[0] not in ("-u", "-r32"):
            raise ValueError("Read-only SWD operation required")
        if tokens[0] == "-u":
            if len(tokens) != 4 or tokens[1:3] != ["0x08000000", "0x80000"]:
                raise ValueError("Complete private backup only")
        elif len(tokens) % 3 or any(tokens[i] != "-r32" or tokens[i+2] != "4"
                                   for i in range(0, len(tokens), 3)):
            raise ValueError("Read-only 32-bit register list required")
        p = subprocess.run([CLI, "-c", "port=SWD", "mode=HOTPLUG", "freq=1000",
                            "sn=" + SN, *tokens], capture_output=True, text=True,
                           errors="replace", timeout=30)
        out = p.stdout + p.stderr
        record["steps"].append({"args": tokens, "code": p.returncode, "output": out})
        if p.returncode or "Error:" in out:
            raise RuntimeError("Read-only SWD failed; no automatic retry/reset")
        return out

    def capture(name):
        dest = private / f"{run_id}-{name}.bin"
        cli("-u", "0x08000000", "0x80000", dest)
        data = dest.read_bytes()
        if len(data) != 0x80000:
            raise RuntimeError("Incomplete private Flash backup")
        return data

    def read(addresses):
        tokens = []
        for address in addresses:
            tokens.extend(("-r32", hex(address), "4"))
        return cli(*tokens)

    try:
        before = capture("before")
        record["baseline"] = base = baseline(before)
        record["before_outputs"] = require_registers(read(ADDRESSES), "A")
        record["before_adc"] = require_injected_registers(read(PATH_ADDRESSES))
        import serial
        port = serial.Serial(port=None, baudrate=115200, timeout=.02, write_timeout=2)
        port.dtr = port.rts = False
        port.port = "COM5"
        port.open()
        uart = StageOnlyUart(port)
        record["before_fw"] = require_confirmed(uart.query("FW STATUS", 3), "A")
        if int(record["before_fw"]["GEN"]) != base["generation"]:
            raise RuntimeError("UART and independent Flash metadata mismatch")
        record["before_zero"] = require_service(uart.query("ZERO STATUS"))
        # No FW END, reset, trial or force-confirm is permitted by this class.
        record["stage_attempted"] = True
        stage(uart, path, DEFAULT_CLIENT, allow_reset=False)
        after = capture("staged")
        record["protected_flash"] = compare_flash(before, after, image, "B", staged=True)
        # Stronger than region-by-region checks: every byte outside B is identical.
        if before[:0x40000] != after[:0x40000] or before[0x78000:] != after[0x78000:]:
            raise RuntimeError("Bytes outside inactive B changed")
        record["all_bytes_outside_b_unchanged"] = True
        record["after_outputs"] = require_registers(read(ADDRESSES), "A")
        record["after_adc"] = require_injected_registers(read(PATH_ADDRESSES))
        record["after_fw"] = require_staged(uart.query("FW STATUS"), base["generation"], image)
        record["after_zero"] = require_service(uart.query("ZERO STATUS"))
        record["pass"] = True
        print("4 A STAGE PASS: exact inactive B read back; locked A preserved and still running.", flush=True)
        print("Not activated: no FW END, reset, trial, sample or motor command.", flush=True)
    except BaseException as error:
        record["failure"] = str(error)
        raise
    finally:
        if uart is not None:
            record["uart"] = uart.lines
        if port is not None:
            port.close()
        evidence.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print("Evidence: " + str(evidence), flush=True)


if __name__ == "__main__":
    main()
