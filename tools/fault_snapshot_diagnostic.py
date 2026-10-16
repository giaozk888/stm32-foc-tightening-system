"""Capture the first 2 A startup trip with motor phases DISCONNECTED.

--prepare is read-only: back up all Flash and prove exact locked A / historic
2 A B. --run explicitly permits one existing bootloader START_TRIAL request,
at most 4 seconds of observation, then return to the ALREADY CONFIRMED A.
No Flash image programming, START, fault clear, parameter write or 4 A image.
The debugger polls a valid-last, immutable 80-byte snapshot without halting
until a fault or the time bound. It then turns outputs off before capture.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import struct
import subprocess
import threading
import time
import zlib

from bounded_speed_stage import PINNED_A, baseline, validate_profile
from firmware_transfer_iap import ROOT, Uart
from tighten_synthetic_swd_recovery import CLI, OCD, SCRIPTS, SN
from zero_retest_deploy import DiagnosticUart, require_confirmed, require_service
from zero_span100_acceptance import ADDRESSES, require_registers

OUTPUT = ROOT / "safety_backups/foc-first-fault-20261009"
A_IMAGE = ROOT / "foc2_app_a/build/AdcDmaRaw20261009/foc2.bin"
B_IMAGE = ROOT / "foc2_app_b/build/PoweredSpeedBounded20261009/foc2.bin"
B_SHA = "ca5da7b228cff1f3c97d636de92cd06eb7c80974d4ff81ac6394174b5905ad17"
SNAP_ADDRESS = 0x20002660
SNAP_SIZE = 80
SNAP_VALID_WORD = SNAP_ADDRESS + 76  # valid is byte 77, committed last by ISR
SNAP_FORMAT = "<8I4i13H4B2x"
SNAP_KEYS = (
    "tick_ms", "adc_seq", "vbus_age_ms", "valid_count", "reject_count",
    "reject_streak", "analog_count", "analog_errors", "iu_mA", "iv_mA",
    "iw_mA", "last_rejected_step", "accepted_u", "accepted_v", "physical_u",
    "physical_v", "zero_u", "zero_v", "vbus_raw", "mu0", "mu1", "mu2",
    "mv0", "mv1", "mv2", "filter_on", "median_count", "vbus_valid", "valid",
)


def images():
    a = A_IMAGE.read_bytes()
    b = validate_profile(B_IMAGE, B_SHA)
    if hashlib.sha256(a).hexdigest() != PINNED_A:
        raise RuntimeError("Exact hard-off fallback A required")
    # Hash is the primary historical-build pin; banner is an additional guard.
    if b"Phase trip      : 2.0A" not in b or b"Phase trip      : 4.0A" in b:
        raise RuntimeError("Historical 2 A protection banner missing")
    return a, b


def validate_before(data, a, b):
    result = baseline(data)
    if data[0x8000:0x8000 + len(a)] != a:
        raise RuntimeError("Confirmed A differs")
    if data[0x40000:0x40000 + len(b)] != b:
        raise RuntimeError("B is not already the exact old 2 A image; do not auto-program")
    return result


def decode_snapshot(data):
    if len(data) != SNAP_SIZE:
        raise RuntimeError("Incomplete snapshot")
    row = dict(zip(SNAP_KEYS, struct.unpack(SNAP_FORMAT, data), strict=True))
    if row["valid"] != 1:
        return {"valid": False, "raw_fields": row}
    if any(not 0 <= row[key] <= 4095 for key in
           ("accepted_u", "accepted_v", "physical_u", "physical_v", "zero_u", "zero_v")):
        raise RuntimeError("Invalid ADC counts in pinned snapshot")
    gain = 3300 / (4095 * 120)
    iu = (row["zero_u"] - row["accepted_u"]) * gain
    iv = (row["zero_v"] - row["accepted_v"]) * gain
    currents = {"U": iu, "V": iv, "W": -(iu + iv)}
    stored = (row["iu_mA"], row["iv_mA"], row["iw_mA"])
    if any(abs(stored_value - calculated * 1000) > 2 for stored_value, calculated in
           zip(stored, currents.values(), strict=True)):
        raise RuntimeError("Stored currents contradict ADC/gain conversion")
    phases = [name for name, current in currents.items() if abs(current) > 2.0]
    if not phases:
        raise RuntimeError("Valid trip snapshot does not exceed original 2 A threshold")
    warmup = row["median_count"] < 3
    return {"valid": True, "raw_fields": row, "count_to_A": gain,
            "calculated_current_A": currents, "trip_phases": phases,
            "median_warmup_at_fault": warmup,
            "first_accepted_frame": row["valid_count"] == 1,
            "accepted_equals_physical": row["accepted_u"] == row["physical_u"] and
                                        row["accepted_v"] == row["physical_v"],
            "median_matches": None if warmup else
                row["accepted_u"] == sorted([row["mu0"], row["mu1"], row["mu2"]])[1] and
                row["accepted_v"] == sorted([row["mv0"], row["mv1"], row["mv2"]])[1],
            "physical_current_or_emi_proven": False}


def mailbox(command):
    # 2 starts B from existing confirmed A; 3 restores ONLY that known A.
    # Never command 1 (confirm the test firmware), never select B as confirmed.
    if command == 2:
        image = B_IMAGE.read_bytes()
        values = (0x584F424D, 1, 2, 1, 2, len(image), zlib.crc32(image))
    elif command == 3:
        values = (0x584F424D, 1, 3, 2, 1, 0, 0)
    else:
        raise ValueError("Only one trial and known-A restoration permitted")
    payload = struct.pack("<7I", *values)
    words = (*values, zlib.crc32(payload))
    return ["mww 0x2001FFC0 0", *[
        f"mww {0x2001FFC0 + i * 4:#x} {words[i]:#x}" for i in range(1, 8)],
        f"mww 0x2001FFC0 {words[0]:#x}"]


def trial_commands(snapshot_path):
    # Only known public firmware paths are interpolated, not user Tcl text.
    return ["init", "halt", "mww 0x48000818 0x00400000",
            'if {[mrw 0xE000ED08] != 0x08008000} {error "Expected locked A"}',
            'if {[mrw 0x48000814] & 0x40 || [mrw 0x40012C44] & 0xC000 || [mrw 0x40012C00] & 1 || [mrw 0x40012C20]} {error "A outputs not locked"}',
            f"verify_image {{{A_IMAGE.as_posix()}}} 0x08008000 bin",
            f"verify_image {{{B_IMAGE.as_posix()}}} 0x08040000 bin",
            *mailbox(2), "reset run", "set task_found 0", "set task_b_start -1",
            # CRC validation is bootloader time, NOT powered APP test time.
            # Protect cleanup from a probe-loop error: always return known A.
            "set task_probe_code [catch {", "set task_begin [ms]",
            f'while {{[ms] - $task_begin < 20000}} {{set task_vtor [mrw 0xE000ED08]; if {{$task_vtor == 0x08040000}} {{if {{$task_b_start < 0}} {{set task_b_start [ms]; echo "B_ENTRY_BOOT_MS=[expr {{$task_b_start - $task_begin}}]"}}; if {{(([mrw {SNAP_VALID_WORD:#x}] >> 8) & 0xFF) == 1}} {{set task_found 1; break}}; if {{[ms] - $task_b_start >= 4000}} {{break}}}}; sleep 10}}',
            "} task_probe_error]",
            "halt",
            # If B never started, bootloader GPIO/TIM clocks may be gated.
            # Establish/read actual OFF registers, not an all-ones bus value.
            "mmw 0x4002104C 0x4 0", "mww 0x48000818 0x00400000",
            "mmw 0x48000800 0x1000 0x2000", "mmw 0x40021060 0x800 0",
            "mww 0x48000818 0x00400000", "mww 0x40012C20 0",
            "mmw 0x40012C44 0 0xC000", "mmw 0x40012C00 0 1",
            'if {[mrw 0x48000814] & 0x40 || [mrw 0x40012C44] & 0xC000 || [mrw 0x40012C00] & 1 || [mrw 0x40012C20]} {error "Output-off failed"}',
            'echo "DIAG HARDWARE LOCK: SD=0 MOE=0 AOE=0 CCER=0 CEN=0"',
            'echo "FIRST_FAULT_VALID=$task_found"', "mdw 0xE000ED08 1",
            "mdw 0xE000ED28 1", "mdb 0x20002648 2", "mdw 0x200026bc 1",
            f"dump_image {{{snapshot_path.as_posix()}}} {SNAP_ADDRESS:#x} {SNAP_SIZE}",
            # The previous confirmed A is verified again, never confirm B.
            f"verify_image {{{A_IMAGE.as_posix()}}} 0x08008000 bin",
            *mailbox(3), "reset run",
            'if {$task_probe_code != 0} {echo "PROBE_LOOP_ERROR=$task_probe_error"}',
            "shutdown"]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--prepare", action="store_true")
    mode.add_argument("--run", type=Path, help="verified prepare JSON")
    parser.add_argument("--drive-12v-off", action="store_true")
    parser.add_argument("--allow-trial-reset", action="store_true")
    parser.add_argument("--drive-12v-on", action="store_true")
    parser.add_argument("--motor-disconnected", action="store_true")
    parser.add_argument("--supply-limit-0p5a", action="store_true")
    args = parser.parse_args()
    # Prepare only reads from the proven locked A; it neither resets nor starts
    # conversions, so it is also safe while the disconnected driver is powered.
    if args.run and not all((args.allow_trial_reset, args.drive_12v_on,
                             args.motor_disconnected, args.supply_limit_0p5a)):
        parser.error("Explicit trial/reset authorization and disconnected phases / 12 V / 0.5 A required")
    a, b = images()  # Fail before all hardware operations if wrong artifact.
    OUTPUT.mkdir(parents=True, exist_ok=True)
    private = OUTPUT / "private-flash"
    private.mkdir(exist_ok=True)
    subprocess.run(["icacls", str(private), "/inheritance:r", "/grant:r",
                    "*S-1-5-18:(OI)(CI)F", "*S-1-5-32-544:(OI)(CI)F"],
                   capture_output=True, text=True, check=True)
    run_id = str(time.time_ns())
    evidence = OUTPUT / f"{'prepare' if args.prepare else 'capture'}-{run_id}.json"
    result = {"prepared": False, "image_programmed": False, "motion_commands": 0,
              "fault_clear": False, "test_b_force_confirmed": False,
              "a_sha256": PINNED_A, "b_sha256": B_SHA, "threshold_A": 2.0,
              "steps": [], "uart": []}
    port = None
    reader = None
    stop_reader = threading.Event()

    def cli(*ops):
        p = subprocess.run([CLI, "-c", "port=SWD", "mode=HOTPLUG", "freq=1000", "sn=" + SN,
                            *map(str, ops)], capture_output=True, text=True, errors="replace", timeout=30)
        result["steps"].append({"args": list(map(str, ops)), "code": p.returncode,
                                "output": p.stdout + p.stderr})
        if p.returncode or "Error:" in p.stdout + p.stderr:
            raise RuntimeError("SWD read failed")
        return p.stdout + p.stderr

    def capture(name):
        path = private / f"{run_id}-{name}.bin"
        cli("-u", "0x08000000", "0x80000", path)
        return path, path.read_bytes()

    def regs():
        ops = [item for address in ADDRESSES for item in ("-r32", hex(address), "4")]
        return require_registers(cli(*ops), "A")

    try:
        prior = None
        if args.run:
            record = args.run.resolve()
            if record.parent != OUTPUT.resolve() or not record.name.startswith("prepare-"):
                raise RuntimeError("Use this diagnostic's prepare record")
            prior = json.loads(record.read_text(encoding="utf-8"))
            if (prior.get("prepared") is not True or prior.get("b_sha256") != B_SHA or
                    prior.get("a_sha256") != PINNED_A or prior.get("threshold_A") != 2.0):
                raise RuntimeError("Preparation does not match pinned images")
            result["prepare_record"] = str(record)
        result["before_registers"] = regs()
        before_path, before = capture("before")
        result["before_flash"] = str(before_path)
        result["baseline"] = validate_before(before, a, b)
        if prior and hashlib.sha256(before).hexdigest() != prior["before_flash_sha256"]:
            raise RuntimeError("Flash changed after preparation; no trial")
        result["before_flash_sha256"] = hashlib.sha256(before).hexdigest()
        import serial
        port = serial.Serial(port=None, baudrate=115200, timeout=.02, write_timeout=1)
        port.dtr = port.rts = False
        port.port = "COM5"
        port.open()
        diag = DiagnosticUart(port)
        result["before_fw"] = require_confirmed(diag.query("FW STATUS", 3), "A")
        result["before_service"] = require_service(diag.query("ZERO STATUS", 3))
        result["before_safe"] = diag.query("ANALOG SAFE STATUS", 3)
        if int(result["before_fw"]["GEN"]) != result["baseline"]["generation"]:
            raise RuntimeError("Flash/UART generation disagreement")
        if args.prepare:
            result["prepared"] = True
            print("PREPARE PASS: read-only; exact old 2 A B reusable; no Flash write/reset/START", flush=True)
            return

        # Observe unsolicited boot UART; no command shares the reader.
        uart = Uart(port)
        def record_uart():
            try:
                while not stop_reader.is_set():
                    line = uart.read_line(.1)
                    if line is not None:
                        if len(result["uart"]) >= 2000:
                            raise RuntimeError("UART evidence bound exceeded")
                        result["uart"].append(line)
                        print("RX " + line, flush=True)
            except Exception as error:
                result["uart_error"] = str(error)
        reader = threading.Thread(target=record_uart, daemon=True)
        reader.start()
        snapshot_path = OUTPUT / f"snapshot-{run_id}.bin"
        result["snapshot_path"] = str(snapshot_path)
        command = "; ".join(trial_commands(snapshot_path))
        result["trial_requested_once"] = True  # attempted, not a success claim
        p = subprocess.run([OCD, "-s", SCRIPTS, "-f", "interface/stlink.cfg",
                            "-f", "target/stm32g4x.cfg", "-c",
                            "gdb_port disabled; tcl_port disabled; telnet_port disabled; "
                            "adapter serial " + SN + "; adapter speed 1000; " + command],
                           capture_output=True, text=True, errors="replace", timeout=40)
        output = p.stdout + p.stderr
        result["steps"].append({"openocd_code": p.returncode, "output": output})
        print(output, flush=True)
        stop_reader.set()
        reader.join(timeout=2)
        reader = None
        if p.returncode or "DIAG HARDWARE LOCK:" not in output:
            raise RuntimeError("Bounded diagnostic SWD sequence failed; no automatic retry")
        valid = "FIRST_FAULT_VALID=1" in output
        result["captured"] = valid
        if valid:
            result["snapshot"] = decode_snapshot(snapshot_path.read_bytes())
            if result["snapshot"]["valid"] is not True:
                raise RuntimeError("Debugger trigger and snapshot valid disagree")
            print("FIRST FAULT SNAPSHOT CAPTURED: " + json.dumps(result["snapshot"], ensure_ascii=False), flush=True)
        else:
            result["snapshot"] = {"valid": False, "cause_determined": False}
            print("NO CURRENT TRIP in the 4 s bound; this does not qualify the current chain", flush=True)
        # Return to known A has completed inside the ONE debug session.
        diag = DiagnosticUart(port)
        until = time.monotonic() + 20
        while True:
            try:
                result["final_fw"] = require_confirmed(diag.query("FW STATUS", .5), "A")
                break
            except TimeoutError:
                if time.monotonic() >= until:
                    raise
        result["final_service"] = require_service(diag.query("ZERO STATUS", 3))
        result["final_safe"] = diag.query("ANALOG SAFE STATUS", 3)
        result["final_registers"] = regs()
        _, actual = capture("final")
        after = validate_before(actual, a, b)
        for name, start, end in (("bootloader", 0, 0x8000), ("A", 0x8000, 0x40000),
                                  ("B_and_KVS", 0x40000, 0x7E800),
                                  ("parameters", 0x7F800, 0x80000)):
            if actual[start:end] != before[start:end]:
                raise RuntimeError("Protected Flash region changed: " + name)
        if after["generation"] <= result["baseline"]["generation"]:
            raise RuntimeError("Known-A restoration metadata not committed")
        result["protected_flash_unchanged"] = True
        result["returned_to_locked_a"] = True
        print("DIAG FINAL PASS: confirmed locked A; all image/data regions unchanged; no START", flush=True)
    except BaseException as error:
        result["failure"] = str(error)
        raise
    finally:
        stop_reader.set()
        if reader:
            reader.join(timeout=2)
        if port:
            port.close()
        evidence.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print("Evidence: " + str(evidence), flush=True)


if __name__ == "__main__":
    main()
