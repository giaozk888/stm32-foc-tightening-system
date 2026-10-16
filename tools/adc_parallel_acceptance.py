"""Pinned, hard-off parallel three-ADC diagnostic deployment through UART pw_transfer.

Inspection is read-only. Deployment needs explicit permission and drive power
OFF. Preserve the entire confirmed locked fallback, bootloader and parameters.
Only exact locked old raw, sequential and parallel artifacts are admitted. No motor command, sampling or forced confirmation.
"""
import argparse
import hashlib
import json
import re
import subprocess
import time
import zlib

from firmware_transfer_iap import ROOT, DEFAULT_CLIENT, image_info, stage
from zero_retest_deploy import CLI, SN, latest_meta, compare_flash, require_confirmed, require_service
from zero_span100_acceptance import (
    BASES, ADDRESSES, AcceptanceUart, require_registers, require_new_service,
    observe_trial, await_confirmed_console,
)
from zero_async_clock_acceptance import locked_baseline
from adc_parallel_clock import CLOCK_ADDRESSES, require_async_registers
from adc_three_phase_acceptance import PINNED as SEQUENTIAL_PINNED
from adc_parallel_report import require_status

PINNED = {
    "A": "645cc991604a88a18a06787c1ce8fd295b914f054516e53fd863028de19d05dc",
    "B": "f0467cd9254bb93339986457448d5e4d1a57535b318685688e48e9373c9b1a63",
}
OLD_RAW = {
    "A": "fb98a49edeec94b696d616e990f822f1a8c10dccfd12f0308510e1747cda52ac",
    "B": "2404953e04567b896a2bc17eb5440a661110c75316626805e9197a90c6495ff0",
}
OUTPUT = ROOT / "safety_backups/adc-parallel-live-20261010"


def pinned_image(slot):
    path = ROOT / f"foc2_app_{slot.lower()}/build/AdcParallel20261010/foc2.bin"
    image = path.read_bytes()
    if image_info(image)[0] != slot or hashlib.sha256(image).hexdigest() != PINNED[slot]:
        raise RuntimeError("Exact offline-verified parallel three-ADC locked image required")
    return path, image


def diagnostic_baseline(data):
    # Both slots must be exact output-locked artifacts. No normal motor image.
    known = {slot: frozenset((OLD_RAW[slot], SEQUENTIAL_PINNED[slot], PINNED[slot]))
             for slot in "AB"}
    return locked_baseline(data, known=known)


class ParallelUart(AcceptanceUart):
    def __init__(self, port):
        super().__init__(port)
        self.sample_commands = 0

    def raw_query(self, command, timeout=2):
        if command == "ADC PAR SAMPLE":
            if self.sample_commands:
                raise RuntimeError("No repeated/automatic sample allowed")
            self.sample_commands += 1
        elif command != "ADC PAR STATUS" and not re.fullmatch(r"ADC PAR READ \d+", command):
            raise ValueError("Unsupported parallel three-ADC diagnostic command")
        self.request += 1
        request = self.request
        self.port.write(f"{request} {command}\r\n".encode("ascii"))
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            line = self.read_line(.05)
            if line is None:
                continue
            self.dispatch(line)
            if line.startswith(f"{request} "):
                if not line.startswith(f"{request} OK "):
                    raise RuntimeError(line)
                return line
        raise TimeoutError("No ACK; do not resend acquisition: " + command)


def require_fresh_parallel(uart):
    zero = require_new_service(uart.query("ZERO STATUS"))
    raw = require_status(uart.raw_query("ADC PAR STATUS"))
    if any(raw.get(k) != v for k, v in (
            ("STATE", "0"), ("REASON", "0"), ("CEN", "0"),
            ("NU", "0"), ("NV", "0"), ("NW", "0"), ("IRQ", "0,0,0"), ("ERR", "0,0,0"))):
        raise RuntimeError("Fresh, unsampled parallel three-ADC diagnostic required")
    return {"zero": zero, "raw": raw}


def main(*, image_provider=pinned_image, baseline_checker=diagnostic_baseline,
         fresh_checker=require_fresh_parallel, image_hashes=PINNED,
         output_dir=OUTPUT, profile="PARALLEL", clock_addresses=CLOCK_ADDRESSES,
         clock_checker=require_async_registers):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inspect", action="store_true")
    parser.add_argument("--allow-deploy", action="store_true")
    parser.add_argument("--drive-12v-off", action="store_true")
    parser.add_argument("--restart-verified-diagnostic", action="store_true")
    args = parser.parse_args()
    if args.inspect == args.allow_deploy:
        parser.error("Select read-only inspection OR explicit deployment")
    if args.allow_deploy and not args.drive_12v_off:
        parser.error("Drive 12 V must physically be OFF while deploying")
    if args.restart_verified_diagnostic and not args.allow_deploy:
        parser.error("Read-only inspection cannot reset")
    artifacts = {slot: image_provider(slot) for slot in "AB"}
    if args.allow_deploy and not DEFAULT_CLIENT.is_file():
        parser.error("Official native transfer client missing")
    output_dir.mkdir(parents=True, exist_ok=True)
    private = output_dir / "private"
    private.mkdir(exist_ok=True)
    subprocess.run(["icacls", str(private), "/inheritance:r", "/grant:r",
                    "*S-1-5-18:(OI)(CI)F", "*S-1-5-32-544:(OI)(CI)F"],
                   check=True, capture_output=True, text=True)
    run_id = str(time.time_ns())
    target = output_dir / f"deployment-{run_id}.json"
    result = {"pass": False, "inspect_only": args.inspect, "steps": [],
              "motion_commands": False, "sampling_commands": False,
              "zero_qualified": False, "motor_qualified": False,
              "force_confirm": False, "direct_metadata_write": False,
              "physical_drive_off_user_confirmed": args.drive_12v_off,
              "profile": profile}
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
            raise RuntimeError("SWD operation failed; no automatic retry")
        return out

    def capture(name):
        path = private / f"{run_id}-{name}.bin"
        cli("-u", "0x08000000", "0x80000", path)
        data = path.read_bytes()
        if len(data) != 0x80000:
            raise RuntimeError("Incomplete private Flash capture")
        return data

    def read(addresses):
        command = []
        for address in addresses:
            command.extend(("-r32", hex(address), "4"))
        return cli(*command)

    def registers(slot):
        return require_registers(read(ADDRESSES), slot)

    try:
        before = capture("before")
        baseline = baseline_checker(before)
        result["baseline"] = baseline
        current = baseline["current"]
        result["before_registers"] = registers(current)
        if args.inspect:
            result["pass"] = True
            print("READ-ONLY PASS: exact locked confirmed " + current + "; inactive image classified")
            return
        import serial
        port = serial.Serial(port=None, baudrate=115200, timeout=.02, write_timeout=2)
        port.dtr = port.rts = False
        port.port = "COM5"
        port.open()
        uart = ParallelUart(port)
        try:
            fw = uart.query("FW STATUS", 3)
        except TimeoutError:
            if not args.restart_verified_diagnostic:
                raise
            # Re-read exact Flash and output bits immediately before the one
            # explicitly permitted reset; no normal motor image is admitted.
            if capture("before-console-reset") != before:
                raise RuntimeError("Flash changed before guarded console restart")
            result["console_restart_registers"] = registers(current)
            result["console_recovery_reset"] = True
            cli("-rst")
            await_confirmed_console(uart, current)
            fw = uart.query("FW STATUS", 3)
        result["before_fw"] = require_confirmed(fw, current)
        if int(result["before_fw"]["GEN"]) != baseline["generation"]:
            raise RuntimeError("UART metadata differs from independent Flash read")
        result["before_zero"] = require_service(uart.query("ZERO STATUS"))
        slot = "B" if current == "A" else "A"
        path, image = artifacts[slot]
        if hashlib.sha256(image).hexdigest() != image_hashes[slot]:
            raise RuntimeError("Target profile image hash mismatch; no staging")
        result.update(target_slot=slot, image_sha256=image_hashes[slot], image_size=len(image))
        stage(uart, path, DEFAULT_CLIENT, allow_reset=False)
        staged = capture("staged")
        result["staged_flash"] = compare_flash(before, staged, image, slot, staged=True)
        result["staged_registers"] = registers(current)
        try:
            uart.command("FW END", timeout=20)
            result["fw_end_ack"] = True
        except TimeoutError:
            # It may already have reset. Observe once; never repeat END.
            result["fw_end_ack"] = False
            print("FW END ACK uncertain; observing existing trial, no resend", flush=True)
        result["trial_reset_requested"] = True
        result["confirmed_fw"] = observe_trial(uart, slot)
        result["three_phase_service"] = fresh_checker(uart)
        result["final_fw"] = require_confirmed(uart.query("FW STATUS"), slot)
        result["final_registers"] = registers(slot)
        result["async_clock_registers"] = clock_checker(read(clock_addresses))
        final = capture("final")
        result["final_flash"] = compare_flash(before, final, image, slot)
        result["pass"] = True
        print(profile + " LOCKED DEPLOYMENT PASS: confirmed " + slot +
              "; exact fallback preserved; no sample or motor action", flush=True)
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
