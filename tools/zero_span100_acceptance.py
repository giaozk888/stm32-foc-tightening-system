"""Install one pinned span-100, output-locked diagnostic APP via official IAP.

No hardware access without --inspect or explicit --allow-deploy plus
--drive-12v-off. --inspect never resets/writes Flash. A separately selected
--restart-verified-diagnostic permits one reset of an exact confirmed locked
diagnostic image if its console does not answer. No sampling or motor commands.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import time
import zlib

from firmware_transfer_iap import ROOT, Uart, stage, image_info, DEFAULT_CLIENT
from zero_retest_deploy import (
    CLI, SN, PINNED as OLD_PINNED, DiagnosticUart, compare_flash,
    latest_meta, require_confirmed, require_service,
)

OUTPUT = ROOT / "safety_backups/zero-span100-20261009"
PINNED = {
    "A": "e7629ef0861dfd11d26285729c3a0decd05854d92382d677fbe3733286e56223",
    "B": "d013cea90dcd22ab9c2dd487a940b19a2e94087e57518f193436aeb02383b7ed",
}
BASES = {"A": 0x08008000, "B": 0x08040000}
ADDRESSES = (0xE000ED08, 0x48000814, 0x40012C44, 0x40012C00,
             0x40012C20, 0xE000ED28)


def locked_baseline(data):
    if len(data) != 0x80000:
        raise RuntimeError("Complete baseline capture required")
    meta = latest_meta(data)
    if meta[2] not in (1, 2) or meta[3:5] != (0, 0):
        raise RuntimeError("Need confirmed diagnostic with no pending trial")
    images = {}
    for slot, index in (("A", 6), ("B", 8)):
        size, crc = meta[index:index + 2]
        if not 8 <= size <= 0x38000:
            raise RuntimeError("Diagnostic image size missing/invalid")
        start = BASES[slot] - 0x08000000
        image = data[start:start + size]
        sha = hashlib.sha256(image).hexdigest()
        if (image_info(image)[0] != slot or zlib.crc32(image) != crc or
                sha not in (OLD_PINNED[slot], PINNED[slot])):
            raise RuntimeError("Both slots must be exact known locked diagnostics")
        images[slot] = {"bytes": size, "crc32": f"{crc:08X}", "sha256": sha}
    return {"current": "A" if meta[2] == 1 else "B",
            "generation": meta[5], "images": images}


def require_registers(output, slot):
    regs = {int(a, 16): int(v, 16) for a, v in
            re.findall(r"(?im)^0x([0-9A-F]+)\s*:\s*([0-9A-F]{8})\s*$", output)}
    if (set(regs) != set(ADDRESSES) or regs[0xE000ED08] != BASES[slot] or
            regs[0x48000814] & 0x40 or regs[0x40012C44] & 0xC000 or
            regs[0x40012C00] & 1 or regs[0x40012C20] or regs[0xE000ED28]):
        raise RuntimeError("Independent MCU output/fault proof failed")
    return {f"0x{a:08X}": f"{v:08X}" for a, v in regs.items()}


def require_new_service(line):
    row = require_service(line)
    if any(row.get(k) != v for k, v in
           (("SPAN", "100"), ("ADC_READY", "1"), ("STATE", "0"),
            ("REASON", "0"), ("ADC", "0"), ("N", "0"), ("SET", "0"))):
        raise RuntimeError("Expected fresh, unsampled span-100 diagnostic")
    return row


def pinned_image(slot):
    path = ROOT / f"foc2_app_{slot.lower()}/build/ZeroSpan10020261009/foc2.bin"
    image = path.read_bytes()
    if image_info(image)[0] != slot or hashlib.sha256(image).hexdigest() != PINNED[slot]:
        raise RuntimeError("Only exact offline-verified diagnostic image admitted")
    return path, image


class AcceptanceUart(DiagnosticUart):
    def dispatch(self, line):
        super().dispatch(line)
        Uart.dispatch(self, line)  # Deliver pw_transfer RPC replies to native client.


def await_confirmed_console(uart, slot, timeout=8):
    """Bounded read-only polling: a request sent before RX init can be lost."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            return require_confirmed(uart.query("FW STATUS", .5), slot)
        except TimeoutError:
            continue
    raise TimeoutError("Confirmed diagnostic console did not become ready")


def observe_trial(uart, slot):
    deadline = time.monotonic() + 35
    seen = False
    while time.monotonic() < deadline:
        try:
            zero = uart.query("ZERO STATUS", .5)
            require_service(zero)
            fw = uart.query("FW STATUS", .5)
        except TimeoutError:
            continue
        current = require_service(zero)
        if current.get("IF") != "0":
            raise RuntimeError("Diagnostic interlock fault")
        if re.search(r"\bCURRENT=" + slot + r"\b", fw) is None:
            if seen:
                raise RuntimeError("Trial rolled back; do not retry/reset")
            continue
        seen = True
        require_new_service(zero)
        if re.search(r"\bCONFIRMED=" + slot + r"\b", fw) and "PENDING=-" in fw:
            return require_confirmed(fw, slot)
        uart.poll(.1)
    raise TimeoutError("No normal diagnostic confirmation; never force-confirm")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inspect", action="store_true")
    parser.add_argument("--allow-deploy", action="store_true")
    parser.add_argument("--drive-12v-off", action="store_true")
    parser.add_argument("--restart-verified-diagnostic", action="store_true")
    args = parser.parse_args()
    if args.inspect == args.allow_deploy:
        parser.error("Choose read-only --inspect OR explicitly authorized --allow-deploy")
    if args.allow_deploy and not args.drive_12v_off:
        parser.error("Deployment requires drive 12 V physically OFF")
    if args.restart_verified_diagnostic and not args.allow_deploy:
        parser.error("Read-only inspection cannot reset")
    # Validate build artifacts before any probe or serial access.
    images = {slot: pinned_image(slot) for slot in "AB"}
    if args.allow_deploy and not DEFAULT_CLIENT.is_file():
        parser.error("Official transfer client missing")
    OUTPUT.mkdir(parents=True, exist_ok=True)
    private = OUTPUT / "private"
    private.mkdir(exist_ok=True)
    # Complete Flash backups may contain secrets. Restrict BEFORE writing bytes.
    subprocess.run(["icacls", str(private), "/inheritance:r", "/grant:r",
                    "*S-1-5-18:(OI)(CI)F", "*S-1-5-32-544:(OI)(CI)F"],
                   check=True, capture_output=True, text=True)
    run_id = str(time.time_ns())
    target = OUTPUT / f"acceptance-{run_id}.json"
    result = {"pass": False, "inspect_only": args.inspect, "motion_commands": False,
              "sampling_commands": False, "zero_qualified": False,
              "motor_qualified": False, "force_confirm": False,
              "direct_metadata_write": False, "steps": []}
    uart = None
    port = None

    def cli(*arguments):
        process = subprocess.run(
            [CLI, "-c", "port=SWD", "mode=HOTPLUG", "freq=1000", "sn=" + SN,
             *map(str, arguments)], capture_output=True, text=True,
            errors="replace", timeout=30)
        output = process.stdout + process.stderr
        result["steps"].append({"tool": "CLI", "args": list(map(str, arguments)),
                                "code": process.returncode, "output": output})
        if process.returncode or "Error:" in output:
            raise RuntimeError("SWD operation failed; no automatic retry")
        return output

    def capture(name):
        path = private / f"{run_id}-{name}.bin"
        cli("-u", "0x08000000", "0x80000", path)
        data = path.read_bytes()
        if len(data) != 0x80000:
            raise RuntimeError("Incomplete Flash capture")
        return data

    def registers(slot):
        arguments = []
        for address in ADDRESSES:
            arguments.extend(("-r32", hex(address), "4"))
        return require_registers(cli(*arguments), slot)

    try:
        before = capture("before")
        baseline = locked_baseline(before)
        result["baseline"] = baseline
        current = baseline["current"]
        result["before_registers"] = registers(current)
        if args.inspect:
            result["pass"] = True
            print("READ-ONLY PASS: both exact locked diagnostics, confirmed " + current)
            return
        import serial
        port = serial.Serial(port=None, baudrate=115200, timeout=.02, write_timeout=2)
        port.dtr = port.rts = False
        port.port = "COM5"
        port.open()
        uart = AcceptanceUart(port)
        try:
            fw = uart.query("FW STATUS", 3)
        except TimeoutError:
            if not args.restart_verified_diagnostic:
                raise
            # Only a verified confirmed hard-off profile may be restarted, once.
            registers(current)
            result["console_recovery_reset"] = True
            cli("-rst")
            fw = await_confirmed_console(uart, current)
            # The helper returns parsed fields; fetch a complete line for the
            # common confirmation check below. Both operations are read-only.
            fw = uart.query("FW STATUS")
        require_confirmed(fw, current)
        result["before_zero"] = require_service(uart.query("ZERO STATUS"))
        slot = "A" if current == "B" else "B"
        path, image = images[slot]
        result["target_slot"] = slot
        result["image_sha256"] = PINNED[slot]
        result["image_size"] = len(image)
        # Stage first, without reset. Compare full Flash before FW END admission.
        stage(uart, path, DEFAULT_CLIENT, allow_reset=False)
        staged = capture("staged")
        result["staged_flash"] = compare_flash(before, staged, image, slot, staged=True)
        result["staged_registers"] = registers(current)
        uart.command("FW END", timeout=20)
        result["trial_reset_requested"] = True
        result["confirmed_fw"] = observe_trial(uart, slot)
        observations = []
        for _ in range(30):
            observations.append(require_new_service(uart.query("ZERO STATUS")))
            time.sleep(.3)
        result["after_zero"] = observations
        result["final_fw"] = require_confirmed(uart.query("FW STATUS"), slot)
        result["final_registers"] = registers(slot)
        final = capture("final")
        result["final_flash"] = compare_flash(before, final, image, slot)
        result["pass"] = True
        print("SPAN100 DEPLOYMENT PASS: confirmed " + slot +
              "; outputs locked; no zero sampling or motor qualification")
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
