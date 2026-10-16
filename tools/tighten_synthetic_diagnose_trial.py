"""One diagnostic trial of the EXACT existing isolated synthetic A image.

Default makes no hardware operation. Explicit permission allows SRAM
START_TRIAL + reset only, never host Flash programming, forced confirmation,
fault clearing or motion commands. Failed trial returns through the existing
bootloader to unchanged B; the local console then latches B output off.
The bootloader updates its normal trial/rollback metadata in Flash.
"""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import subprocess
import time
import zlib

from firmware_transfer_iap import ROOT, fields, image_info
from powered_boot_probe import read_staged_hardware_safe
from tighten_synthetic_acceptance import SyntheticUart, confirmed, locked
from tighten_synthetic_swd_recovery import latest_meta, OCD, SCRIPTS, SN


def verify_existing(before, actual, image):
    if len(before) != 0x80000 or len(actual) != 0x80000 or image_info(image)[0] != "A":
        raise RuntimeError("Need complete backups and an exact A image")
    if latest_meta(actual)[2:5] != (2, 0, 0):
        raise RuntimeError("Need confirmed B, no pending image/attempts")
    if actual[0x8000:0x8000 + len(image)] != image:
        raise RuntimeError("Existing A differs from the built synthetic image")
    for start, end in ((0, 0x8000), (0x40000, 0x7E800), (0x7F800, 0x80000)):
        if actual[start:end] != before[start:end]:
            raise RuntimeError("Bootloader/B/KVS/parameters differ from the original backup")
    meta = latest_meta(actual)
    # A rejected trial is deliberately retired as size=CRC=0 by the existing
    # bootloader. Do not select it as confirmed. This diagnostic submits a NEW
    # ordinary START_TRIAL with the independently read-back size/CRC; bootloader
    # revalidates the complete image and still requires the same health gate.
    if meta[6:8] not in ((0, 0), (len(image), zlib.crc32(image))):
        raise RuntimeError("Unexpected existing A metadata")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--allow-existing-isolated-trial", action="store_true")
    args = parser.parse_args()
    if not args.allow_existing_isolated_trial:
        parser.error("No operation without isolated reset/trial authorization")
    output = ROOT / "safety_backups/tighten-synthetic-20261008"
    target = output / "health-diagnostic.json"
    if target.exists():
        raise RuntimeError("One diagnostic only; preserve the prior evidence")
    private = output / "private"
    before = (private / "before-flash.bin").read_bytes()
    actual = (private / "before-health-diagnose.bin").read_bytes()
    image_path = ROOT / "foc2_app_a/build/TightenSyntheticIsolated/foc2.bin"
    image = image_path.read_bytes()
    verify_existing(before, actual, image)
    crc = zlib.crc32(image)
    record = {"image_sha256": hashlib.sha256(image).hexdigest(),
              "host_flash_programming": False, "bootloader_metadata_updates": True,
              "force_confirm": False, "fault_clearing": False,
              "motion_commands": False, "trial_confirmed": False, "rollback_locked": False}
    import serial
    port = serial.Serial(port=None, baudrate=115200, timeout=0.02, write_timeout=1)
    port.dtr = port.rts = False
    port.port = "COM5"
    uart = None
    trial_requested = False
    try:
        port.open()
        uart = SyntheticUart(port)
        uart.request = 66000
        if not confirmed(fields(uart.query("FW STATUS")), "B"):
            raise RuntimeError("Current UART does not prove confirmed B")
        if not locked(fields(uart.query("ANALOG SAFE STATUS"))):
            raise RuntimeError("B must already be locked off")
        state = fields(uart.query("STATUS"))
        if any(state.get(k) != v for k, v in (("MODE", "IDLE"), ("BUSY", "0"), ("FLT", "0"))):
            raise RuntimeError("B is not idle/fault-free; do not clear anything")
        read_staged_hardware_safe()
        packet = struct.pack("<7I", 0x584F424D, 1, 2, 2, 1, len(image), crc)
        words = struct.unpack("<8I", packet + struct.pack("<I", zlib.crc32(packet)))
        # One session: verify unchanged A, reset/halt in bootloader, establish
        # OFF GPIO/timer state, write only the existing START_TRIAL SRAM request.
        command = ["init", "halt", f"verify_image {{{image_path.as_posix()}}} 0x08008000 bin",
                   "reset halt", "set task_vtor [mrw 0xE000ED08]",
                   'if {$task_vtor != 0 && $task_vtor != 0x08000000} {error "Not in bootloader"}',
                   "mmw 0x4002104C 0x4 0", "mww 0x48000818 0x00400000",
                   "mmw 0x48000800 0x1000 0x2000", "mmw 0x40021060 0x800 0",
                   "mww 0x40012C20 0", "mww 0x40012C44 0", "mww 0x40012C00 0",
                   'if {[mrw 0x48000814] & 0x40 || [mrw 0x40012C44] & 0xC000 || [mrw 0x40012C00] & 1 || [mrw 0x40012C20]} {error "Not OFF"}',
                   "mww 0x2001FFC0 0"]
        command += [f"mww {0x2001FFC0 + i * 4:#x} {words[i]:#x}" for i in range(1, 8)]
        command += [f"mww 0x2001FFC0 {words[0]:#x}", "reset run", "shutdown"]
        p = subprocess.run([OCD, "-s", SCRIPTS, "-f", "interface/stlink.cfg", "-f", "target/stm32g4x.cfg",
                            "-c", "gdb_port disabled; tcl_port disabled; telnet_port disabled; adapter serial " +
                            SN + "; adapter speed 1000; " + "; ".join(command)],
                           capture_output=True, text=True, errors="replace", timeout=35)
        record["debug_output"] = p.stdout + p.stderr
        print(record["debug_output"], flush=True)
        if p.returncode:
            raise RuntimeError("Diagnostic trial request failed; do not retry")
        trial_requested = True
        deadline = time.monotonic() + 55
        seen_a = False
        diagnosed = False
        while time.monotonic() < deadline:
            try:
                fw = fields(uart.query("FW STATUS", timeout=1))
            except TimeoutError:
                continue
            if fw.get("CURRENT") == "A":
                seen_a = True
                if not diagnosed:
                    for text in ("STATUS", "FAULT SNAPSHOT", "FAULT FILTER", "ENC DIAG", "BENCH STATUS", "BENCH STACK"):
                        try:
                            uart.query(text, timeout=1)
                        except (TimeoutError, RuntimeError) as error:
                            record.setdefault("diagnostic_errors", []).append(str(error))
                    diagnosed = True
                if confirmed(fw, "A"):
                    # This fixture's startup is hard-locked; no SIM RUN here.
                    record["trial_confirmed"] = True
                    if not locked(fields(uart.query("ANALOG SAFE STATUS"))):
                        raise RuntimeError("Confirmed fixture not locked off")
                    print("DIAGNOSTIC: A confirmed by existing health checks; no model run", flush=True)
                    return
            elif seen_a and confirmed(fw, "B"):
                record["rollback_locked"] = locked(fields(uart.query("ANALOG SAFE")))
                uart.query("STATUS")
                uart.query("ANALOG SAFE STATUS")
                if not record["rollback_locked"]:
                    raise RuntimeError("Rollback B output lock failed")
                print("DIAGNOSTIC: health rejected A; restored B locked off", flush=True)
                return
            time.sleep(0.25)
        raise TimeoutError("Diagnostic trial did not terminate; no forced confirmation")
    except BaseException as error:
        record["error"] = str(error)
        if trial_requested and uart is not None:
            # Off-only local command; never clear fault/reset or force a slot.
            try:
                record["error_cleanup_locked"] = locked(fields(uart.query("ANALOG SAFE")))
            except Exception as cleanup:
                record["cleanup_error"] = str(cleanup)
        raise
    finally:
        if uart is not None:
            record["uart_evidence"] = uart.evidence
            record["uart_lines"] = uart.uart_lines
        port.close()
        target.write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
