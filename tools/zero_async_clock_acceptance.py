"""Pinned async-ADC diagnostic deployment; never acquires samples or moves a motor.

Read-only --inspect or explicit --allow-deploy --drive-12v-off are required.
Use official UART pw_transfer to stage the inactive APP, compare protected
Flash before FW END, then observe normal A/B locked-service confirmation.
No SWD reset/programming, force-confirm, fault clearing or automatic retries.
"""
import argparse
import hashlib
import json
import re
import subprocess
import time
import zlib

from firmware_transfer_iap import ROOT, DEFAULT_CLIENT, image_info, stage
from zero_retest_deploy import (
    CLI, SN, PINNED as ORIGINAL_PINNED, compare_flash, latest_meta,
    require_confirmed, require_service,
)
from zero_span100_acceptance import (
    PINNED as SPAN100_PINNED, ADDRESSES, BASES, AcceptanceUart,
    require_registers, require_new_service, observe_trial,
)
from foc_adc_ram_test import require_async_adc_clock

PINNED = {
    "A": "342b7a4cede8d0812732222593ba89cc081e7a14d3ede058e5a3dbad56263c60",
    "B": "27d0654bf9663efcda1d805352f8f55d847a1bdc565e4e6d122320ee02e6a465",
}
KNOWN = {slot: frozenset((ORIGINAL_PINNED[slot], SPAN100_PINNED[slot], PINNED[slot]))
         for slot in "AB"}
OUTPUT = ROOT / "safety_backups/zero-async-clock-live-20261009"
CLOCK_ADDRESSES = (0x50000308, 0x40021088, 0x40012C28, 0x40012C2C)


def pinned_image(slot):
    path = ROOT / f"foc2_app_{slot.lower()}/build/ZeroAsyncClock20261009/foc2.bin"
    image = path.read_bytes()
    if image_info(image)[0] != slot or hashlib.sha256(image).hexdigest() != PINNED[slot]:
        raise RuntimeError("Exact offline-verified async locked image required")
    return path, image


def locked_baseline(data, known=KNOWN):
    if len(data) != 0x80000:
        raise RuntimeError("Complete baseline capture required")
    meta = latest_meta(data)
    if meta[2] not in (1, 2) or meta[3:5] != (0, 0):
        raise RuntimeError("Confirmed locked diagnostic with no pending trial required")
    images = {}
    for slot, index in (("A", 6), ("B", 8)):
        size, crc = meta[index:index + 2]
        if not 8 <= size <= 0x38000:
            raise RuntimeError("Invalid stored image length")
        offset = BASES[slot] - 0x08000000
        image = data[offset:offset + size]
        sha = hashlib.sha256(image).hexdigest()
        if (sha not in known[slot] or image_info(image)[0] != slot or
                zlib.crc32(image) != crc):
            raise RuntimeError("Both APPs must be exact known output-locked images")
        images[slot] = {"bytes": size, "crc32": f"{crc:08X}", "sha256": sha}
    return {"current": "A" if meta[2] == 1 else "B",
            "generation": meta[5], "images": images}


def require_async_registers(output):
    regs = {int(a, 16): int(v, 16) for a, v in
            re.findall(r"(?im)^0x([0-9A-F]+)\s*:\s*([0-9A-F]{8})\s*$", output)}
    if set(regs) != set(CLOCK_ADDRESSES):
        raise RuntimeError("Incomplete independent clock/timer readback")
    require_async_adc_clock(regs[0x50000308], regs[0x40021088])
    if regs[0x40012C28] != 0 or regs[0x40012C2C] != 4249:
        raise RuntimeError("TIM1 geometry changed")
    return {f"0x{a:08X}": f"{v:08X}" for a, v in regs.items()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inspect", action="store_true")
    parser.add_argument("--allow-deploy", action="store_true")
    parser.add_argument("--drive-12v-off", action="store_true")
    args = parser.parse_args()
    if args.inspect == args.allow_deploy:
        parser.error("Select read-only inspection OR explicit deployment")
    if args.allow_deploy and not args.drive_12v_off:
        parser.error("Drive 12 V must physically be OFF while deploying")
    artifacts = {slot: pinned_image(slot) for slot in "AB"}
    if args.allow_deploy and not DEFAULT_CLIENT.is_file():
        parser.error("Official native transfer client missing")
    OUTPUT.mkdir(parents=True, exist_ok=True)
    private = OUTPUT / "private"
    private.mkdir(exist_ok=True)
    subprocess.run(["icacls", str(private), "/inheritance:r", "/grant:r",
                    "*S-1-5-18:(OI)(CI)F", "*S-1-5-32-544:(OI)(CI)F"],
                   check=True, capture_output=True, text=True)
    run_id = str(time.time_ns())
    target = OUTPUT / f"deployment-{run_id}.json"
    result = {"pass": False, "inspect_only": args.inspect, "steps": [],
              "motion_commands": False, "sampling_commands": False,
              "zero_qualified": False, "motor_qualified": False,
              "force_confirm": False, "direct_metadata_write": False,
              "physical_drive_off_user_confirmed": args.drive_12v_off}
    port = uart = None

    def cli(*arguments):
        process = subprocess.run(
            [CLI, "-c", "port=SWD", "mode=HOTPLUG", "freq=1000", "sn=" + SN,
             *map(str, arguments)], capture_output=True, text=True,
            errors="replace", timeout=30)
        out = process.stdout + process.stderr
        result["steps"].append({"tool": "CLI", "args": list(map(str, arguments)),
                                "code": process.returncode, "output": out})
        if process.returncode or "Error:" in out:
            raise RuntimeError("SWD inspection failed; no reset/retry")
        return out

    def capture(name):
        path = private / f"{run_id}-{name}.bin"
        cli("-u", "0x08000000", "0x80000", path)
        data = path.read_bytes()
        if len(data) != 0x80000:
            raise RuntimeError("Incomplete private Flash capture")
        return data

    def registers(slot):
        arguments = []
        for address in ADDRESSES:
            arguments.extend(("-r32", hex(address), "4"))
        return require_registers(cli(*arguments), slot)

    def clocks():
        arguments = []
        for address in CLOCK_ADDRESSES:
            arguments.extend(("-r32", hex(address), "4"))
        return require_async_registers(cli(*arguments))

    try:
        before = capture("before")
        baseline = locked_baseline(before)
        result["baseline"] = baseline
        current = baseline["current"]
        result["before_registers"] = registers(current)
        if args.inspect:
            result["pass"] = True
            print("READ-ONLY PASS: known locked images, confirmed " + current)
            return
        import serial
        port = serial.Serial(port=None, baudrate=115200, timeout=.02, write_timeout=2)
        port.dtr = port.rts = False
        port.port = "COM5"
        port.open()
        uart = AcceptanceUart(port)
        result["before_fw"] = require_confirmed(uart.query("FW STATUS", 3), current)
        if int(result["before_fw"]["GEN"]) != baseline["generation"]:
            raise RuntimeError("UART metadata differs from independent Flash read")
        result["before_zero"] = require_service(uart.query("ZERO STATUS"))
        slot = "B" if current == "A" else "A"
        path, image = artifacts[slot]
        result.update(target_slot=slot, image_sha256=PINNED[slot], image_size=len(image))
        stage(uart, path, DEFAULT_CLIENT, allow_reset=False)
        staged = capture("staged")
        result["staged_flash"] = compare_flash(before, staged, image, slot, staged=True)
        result["staged_registers"] = registers(current)
        uart.command("FW END", timeout=20)
        result["trial_reset_requested"] = True
        result["confirmed_fw"] = observe_trial(uart, slot)
        result["after_zero"] = []
        for _ in range(10):
            result["after_zero"].append(require_new_service(uart.query("ZERO STATUS")))
            time.sleep(.3)
        result["final_fw"] = require_confirmed(uart.query("FW STATUS"), slot)
        result["final_registers"] = registers(slot)
        result["async_clock_registers"] = clocks()
        final = capture("final")
        result["final_flash"] = compare_flash(before, final, image, slot)
        result["pass"] = True
        print("ASYNC LOCKED DEPLOYMENT PASS: confirmed " + slot +
              "; async /4 readback verified; no sampling or motor action")
    except BaseException as error:
        result["failure"] = str(error)
        raise
    finally:
        if uart is not None:
            result["uart"] = uart.lines
        if port is not None:
            port.close()
        target.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print("Evidence: " + str(target), flush=True)


if __name__ == "__main__":
    main()
