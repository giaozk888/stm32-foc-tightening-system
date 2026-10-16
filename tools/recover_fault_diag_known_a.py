"""Recover ONLY the previously confirmed, exact hard-off A after probe failure.

Drive 12 V OFF is mandatory. No test B startup, Flash image programming,
test-firmware confirmation, START, protection change or automatic retry.
Existing bootloader service selection returns to the verified known A.
"""
import argparse
import json
from pathlib import Path
import subprocess
import time

from fault_snapshot_diagnostic import OUTPUT, images, mailbox, validate_before
from firmware_transfer_iap import Uart
from tighten_synthetic_swd_recovery import CLI, OCD, SCRIPTS, SN, latest_meta
from zero_retest_deploy import DiagnosticUart, require_confirmed, require_service
from zero_span100_acceptance import ADDRESSES, require_registers


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--failure-record", required=True, type=Path)
    parser.add_argument("--allow-known-a-recovery", action="store_true")
    parser.add_argument("--drive-12v-off", action="store_true")
    args = parser.parse_args()
    if not args.allow_known_a_recovery or not args.drive_12v_off:
        parser.error("Explicit known-A recovery/reset authorization and drive OFF required")
    record_path = args.failure_record.resolve()
    if record_path.parent != OUTPUT.resolve() or not record_path.name.startswith("capture-"):
        raise RuntimeError("Use this diagnostic's failure evidence")
    failed = json.loads(record_path.read_text(encoding="utf-8"))
    if not failed.get("failure"):
        raise RuntimeError("No failed probe to recover")
    before_path = Path(failed["before_flash"]).resolve()
    private = (OUTPUT / "private-flash").resolve()
    if before_path.parent != private:
        raise RuntimeError("Unexpected private baseline")
    before = before_path.read_bytes()
    a, b = images()
    validate_before(before, a, b)
    run_id = str(time.time_ns())
    result = {"known_a_recovered": False, "b_trial_requested_by_recovery": False, "motion_commands": 0,
              "image_programming": False, "test_b_force_confirmed": False, "steps": []}

    def cli(*ops):
        p = subprocess.run([CLI, "-c", "port=SWD", "mode=HOTPLUG", "freq=1000", "sn=" + SN,
                            *map(str, ops)], capture_output=True, text=True, errors="replace", timeout=30)
        result["steps"].append({"ops": list(map(str, ops)), "code": p.returncode,
                                "output": p.stdout + p.stderr})
        if p.returncode or "Error:" in p.stdout + p.stderr:
            raise RuntimeError("Read-only recovery verification failed")
        return p.stdout + p.stderr

    def full(name):
        path = private / f"{run_id}-{name}.bin"
        cli("-u", "0x08000000", "0x80000", path)
        return path.read_bytes()

    def protected(actual):
        if len(actual) != 0x80000:
            raise RuntimeError("Incomplete full Flash")
        for start, end in ((0, 0x7E800), (0x7F800, 0x80000)):
            if actual[start:end] != before[start:end]:
                raise RuntimeError("Image/data region changed; no recovery")
        meta = latest_meta(actual)
        if meta[2] != 1 or meta[6:8] != latest_meta(before)[6:8]:
            raise RuntimeError("Previous confirmed A metadata changed")
        return meta

    port = None
    try:
        state = protected(full("before-recovery"))
        result["before_meta"] = list(state)
        # Read-only proof of halt, bootloader vector, and idle Flash controller.
        cli("-r32", "0xE000EDF0", "4", "-r32", "0xE000ED08", "4", "-r32", "0x40022010", "4")
        from fault_snapshot_diagnostic import A_IMAGE
        snapshot = OUTPUT / f"recovery-snapshot-{run_id}.bin"
        commands = ["init", "halt",
                    'set task_vtor [mrw 0xE000ED08]; echo "RECOVERY_ENTRY_VTOR=$task_vtor"',
                    'if {$task_vtor != 0 && $task_vtor != 0x08000000 && $task_vtor != 0x08040000 && $task_vtor != 0x08008000} {error "Unexpected vector"}',
                    'if {[mrw 0x40022010] & 0x10000} {error "Flash busy; do not reset"}',
                    # Clocks are reset-gated in bootloader: all-ones GPIO reads
                    # are NOT real pin states. Establish explicit SD OFF first.
                    "mmw 0x4002104C 0x4 0", "mww 0x48000818 0x00400000",
                    "mmw 0x48000800 0x1000 0x2000", "mmw 0x40021060 0x800 0",
                    "mww 0x48000818 0x00400000", "mww 0x40012C20 0",
                    "mmw 0x40012C44 0 0xC000", "mmw 0x40012C00 0 1",
                    'if {[mrw 0x48000814] & 0x40 || [mrw 0x40012C44] & 0xC000 || [mrw 0x40012C00] & 1 || [mrw 0x40012C20]} {error "Output lock not proven"}',
                    f'dump_image {{{snapshot.as_posix()}}} 0x20002660 80',
                    f"verify_image {{{A_IMAGE.as_posix()}}} 0x08008000 bin",
                    *mailbox(3), "reset run", "shutdown"]
        p = subprocess.run([OCD, "-s", SCRIPTS, "-f", "interface/stlink.cfg",
                            "-f", "target/stm32g4x.cfg", "-c",
                            "gdb_port disabled; tcl_port disabled; telnet_port disabled; "
                            "adapter serial " + SN + "; adapter speed 1000; " + "; ".join(commands)],
                           capture_output=True, text=True, errors="replace", timeout=15)
        result["steps"].append({"openocd_code": p.returncode, "output": p.stdout + p.stderr})
        print(p.stdout + p.stderr, flush=True)
        if p.returncode:
            raise RuntimeError("Known-A reset request failed; no automatic retry")
        result["snapshot_path"] = str(snapshot)
        import re
        match = re.search(r"RECOVERY_ENTRY_VTOR=(0x[0-9a-fA-F]+|[0-9]+)", p.stdout + p.stderr)
        if not match:
            raise RuntimeError("Missing entry vector evidence")
        result["entry_vector"] = hex(int(match[1], 0))
        result["b_was_running_at_recovery"] = int(match[1], 0) == 0x08040000
        if result["b_was_running_at_recovery"]:
            from fault_snapshot_diagnostic import decode_snapshot
            result["recovery_snapshot"] = decode_snapshot(snapshot.read_bytes())
        import serial
        port = serial.Serial(port=None, baudrate=115200, timeout=.02, write_timeout=1)
        port.dtr = port.rts = False
        port.port = "COM5"
        port.open()
        diag = DiagnosticUart(port)
        until = time.monotonic() + 20
        while True:
            try:
                result["fw"] = require_confirmed(diag.query("FW STATUS", .5), "A")
                break
            except TimeoutError:
                if time.monotonic() >= until:
                    raise
        result["zero"] = require_service(diag.query("ZERO STATUS", 3))
        result["safe"] = diag.query("ANALOG SAFE STATUS", 3)
        result["registers"] = require_registers(cli(*[
            item for address in ADDRESSES for item in ("-r32", hex(address), "4")]), "A")
        result["final_meta"] = list(protected(full("recovered")))
        validate_before((private / f"{run_id}-recovered.bin").read_bytes(), a, b)
        result["known_a_recovered"] = True
        print("RECOVERY PASS: confirmed locked A; original image/data regions unchanged; no new B trial requested", flush=True)
    except BaseException as error:
        result["failure"] = str(error)
        raise
    finally:
        if port:
            port.close()
        out = OUTPUT / f"recovery-{run_id}.json"
        out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print("Evidence: " + str(out), flush=True)


if __name__ == "__main__":
    main()
