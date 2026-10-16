"""Stage a normal APP B from the exact locked APP A, WITHOUT trial/reset/motion.

Requires explicit inactive-slot write authorization and drive 12 V OFF.
Read back all Flash before/after; preserve bootloader, A, data and metadata.
Private full-Flash backups are ACL restricted before capture.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import time
import zlib

from firmware_transfer_iap import ROOT, Uart, DEFAULT_CLIENT, fields, image_info, stage
from zero_retest_deploy import (
    CLI, SN, DiagnosticUart, compare_flash, latest_meta, require_confirmed, require_service,
)
from zero_span100_acceptance import ADDRESSES, require_registers

PINNED_A = "fb98a49edeec94b696d616e990f822f1a8c10dccfd12f0308510e1747cda52ac"
OUTPUT = ROOT / "safety_backups/powered-speed-20261009"


def validate_profile(image_path, expected_sha):
    image = image_path.read_bytes()
    if image_info(image)[0] != "B" or hashlib.sha256(image).hexdigest() != expected_sha:
        raise RuntimeError("Exact APP B image hash/slot mismatch")
    cache = (image_path.parent / "CMakeCache.txt").read_text(encoding="utf-8")
    flags = dict(re.findall(r"(?m)^([A-Z0-9_]+):BOOL=(ON|OFF)$", cache))
    for key, expected in (
        ("ZERO_RETEST_BOOT", "OFF"), ("ADC_DMA_RAW_DIAGNOSTIC", "OFF"),
        ("SAFETY_LOCKED_BOOT", "OFF"), ("FOC_ISOLATED_CONCURRENCY", "OFF"),
        ("TIGHTEN_SYNTHETIC_BENCH", "OFF"), ("TIGHTEN_SPEED_X2_OFFLINE", "OFF"),
        ("FOC_ADC_WINDOW", "OFF"), ("CAN_FD_EXPERIMENT", "OFF"),
        ("CAN_CONTROL_REJECT_ONLY", "ON"), ("CAN_RPC_READ_ONLY", "ON"),
        ("PW_ALLOCATOR_HYBRID", "OFF"), ("UART_FIRMWARE_TRANSFER", "ON"),
    ):
        if flags.get(key) != expected:
            raise RuntimeError("Unexpected normal speed-test profile: " + key)
    if not DEFAULT_CLIENT.is_file():
        raise RuntimeError("Official transfer client missing")
    return image


def baseline(data):
    if len(data) != 0x80000:
        raise RuntimeError("Complete Flash capture required")
    meta = latest_meta(data)
    if meta[2:5] != (1, 0, 0):
        raise RuntimeError("Expected confirmed A with no pending trial")
    size, crc = meta[6:8]
    if not 8 <= size <= 0x38000:
        raise RuntimeError("Invalid fallback A metadata")
    active = data[0x8000:0x8000 + size]
    if (hashlib.sha256(active).hexdigest() != PINNED_A or zlib.crc32(active) != crc
            or image_info(active)[0] != "A"):
        raise RuntimeError("Running fallback must be exact known output-locked A")
    return {"confirmed": "A", "generation": meta[5], "a_sha256": PINNED_A}


class StageUart(DiagnosticUart):
    def dispatch(self, line):
        super().dispatch(line)
        Uart.dispatch(self, line)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", type=Path, required=True)
    parser.add_argument("--sha256", required=True)
    parser.add_argument("--allow-upgrade", action="store_true")
    parser.add_argument("--drive-12v-off", action="store_true")
    args = parser.parse_args()
    if not args.allow_upgrade or not args.drive_12v_off:
        parser.error("Explicit upgrade authorization AND physical drive 12 V OFF required")
    image_path = args.image.resolve()
    image = validate_profile(image_path, args.sha256.lower())
    OUTPUT.mkdir(parents=True, exist_ok=True)
    private = OUTPUT / "private-flash"
    private.mkdir(exist_ok=True)
    subprocess.run(["icacls", str(private), "/inheritance:r", "/grant:r",
                    "*S-1-5-18:(OI)(CI)F", "*S-1-5-32-544:(OI)(CI)F"],
                   check=True, capture_output=True, text=True)
    run_id = str(time.time_ns())
    result_path = OUTPUT / f"stage-{run_id}.json"
    result = {"stage_pass": False, "reset": False, "fw_end": False,
              "motor_commands": False, "force_confirm": False, "steps": [],
              "image": str(image_path), "image_sha256": args.sha256.lower()}
    port = uart = None

    def cli(*arguments):
        p = subprocess.run([CLI, "-c", "port=SWD", "mode=HOTPLUG", "freq=1000", "sn=" + SN,
                            *map(str, arguments)], capture_output=True, text=True,
                           errors="replace", timeout=30)
        output = p.stdout + p.stderr
        result["steps"].append({"args": list(map(str, arguments)), "code": p.returncode,
                                "output": output})
        if p.returncode or "Error:" in output:
            raise RuntimeError("Read-only SWD operation failed")
        return output

    def capture(name):
        path = private / f"{run_id}-{name}.bin"
        cli("-u", "0x08000000", "0x80000", path)
        return path.read_bytes()

    def registers():
        arguments = []
        for address in ADDRESSES:
            arguments.extend(("-r32", hex(address), "4"))
        return require_registers(cli(*arguments), "A")

    try:
        before = capture("before")
        result["baseline"] = baseline(before)
        result["before_registers"] = registers()
        import serial
        port = serial.Serial(port=None, baudrate=115200, timeout=.02, write_timeout=2)
        port.dtr = port.rts = False
        port.port = "COM5"
        port.open()
        uart = StageUart(port)
        result["before_fw"] = require_confirmed(uart.query("FW STATUS", 3), "A")
        if int(result["before_fw"]["GEN"]) != result["baseline"]["generation"]:
            raise RuntimeError("UART/Flash generation mismatch")
        result["before_zero"] = require_service(uart.query("ZERO STATUS"))
        result["before_safe"] = fields(uart.query("ANALOG SAFE STATUS"))
        # No FW END here: the user switches power only after verified staging.
        stage(uart, image_path, DEFAULT_CLIENT, allow_reset=False)
        staged = capture("staged")
        result["flash_comparison"] = compare_flash(before, staged, image, "B", staged=True)
        result["staged_registers"] = registers()
        result["staged_fw"] = fields(uart.query("FW STATUS", 3))
        result["stage_pass"] = True
        print("NORMAL B STAGE PASS: exact readback; fallback A/data/metadata unchanged; "
              "NO FW END, RESET OR START", flush=True)
    except BaseException as error:
        result["failure"] = str(error)
        raise
    finally:
        if port is not None:
            port.close()
        result["uart"] = uart.lines if uart else []
        result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print("Evidence: " + str(result_path), flush=True)


if __name__ == "__main__":
    main()
