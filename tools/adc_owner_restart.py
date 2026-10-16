"""One authorized restart of the exact confirmed, output-locked owner diagnostic.

No Flash writes, acquisition or motor commands. Check public active code before
reset; stop on any mismatch and never retry a reset. Physical motor leads must
be disconnected, with the drive supply confirmed at 12 V/0.5 A and no alarm.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import time

from adc_owner_acceptance import (
    OUTPUT, PINNED, pinned_image, require_owner_service, require_fresh_owner,
)
from adc_owner_sample import deployment_identity
from adc_parallel_acceptance import (
    ParallelUart, CLI, SN, ADDRESSES, CLOCK_ADDRESSES,
    require_registers, require_async_registers,
)
from adc_parallel_report import require_status
from zero_retest_deploy import require_confirmed
from zero_span100_acceptance import BASES


def require_completed(line):
    """Only an intact completed acquisition may be restarted by this tool."""
    return require_status(line, terminal=True)


def require_generation(line, slot, generation):
    row = require_confirmed(line, slot)
    if row.get("GEN") != generation:
        raise RuntimeError("Deployment generation changed; no reset/retry")
    return row


def verify_active_code(code, image, slot):
    if code != image or hashlib.sha256(code).hexdigest() != PINNED[slot]:
        raise RuntimeError("Active code is not the exact pinned locked owner diagnostic")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--deployment-evidence", type=Path, required=True)
    parser.add_argument("--allow-one-reset", action="store_true")
    parser.add_argument("--motor-leads-disconnected", action="store_true")
    parser.add_argument("--supply-12v-0p5a-no-alarm", action="store_true")
    args = parser.parse_args()
    if not all((args.allow_one_reset, args.motor_leads_disconnected,
                args.supply_12v_0p5a_no_alarm)):
        parser.error("Explicit one-reset permission and current physical conditions required")
    evidence = json.loads(args.deployment_evidence.read_text(encoding="utf-8"))
    slot, generation = deployment_identity(evidence)
    _, image = pinned_image(slot)
    OUTPUT.mkdir(parents=True, exist_ok=True)
    prefix = OUTPUT / f"owner-restart-{time.time_ns()}"
    result = {
        "pass": False, "reset_commands": 0, "flash_write": False,
        "sample_commands": 0, "motion_commands": False, "thresholds_changed": False,
        "slot": slot, "image_sha256": PINNED[slot], "steps": [],
        "deployment_evidence": str(args.deployment_evidence),
        "motor_leads_disconnected_user_confirmed": True,
        "supply_12v_0p5a_no_alarm_user_confirmed": True,
    }
    port = uart = None

    def cli(*arguments):
        p = subprocess.run(
            [CLI, "-c", "port=SWD", "mode=HOTPLUG", "freq=1000", "sn=" + SN,
             *map(str, arguments)], capture_output=True, text=True,
            errors="replace", timeout=30)
        output = p.stdout + p.stderr
        result["steps"].append({"args": list(map(str, arguments)),
                                "code": p.returncode, "output": output})
        if p.returncode or "Error:" in output:
            raise RuntimeError("SWD check/reset failed; no automatic reset retry")
        return output

    def hardware():
        def read(addresses):
            arguments = []
            for address in addresses:
                arguments.extend(("-r32", hex(address), "4"))
            return cli(*arguments)
        return {"outputs": require_registers(read(ADDRESSES), slot),
                "clock": require_async_registers(read(CLOCK_ADDRESSES))}

    def fw():
        return require_generation(uart.query("FW STATUS", 1), slot, generation)

    try:
        result["before_hardware"] = hardware()
        import serial
        port = serial.Serial(port=None, baudrate=115200, timeout=.02, write_timeout=1)
        port.dtr = port.rts = False
        port.port = "COM5"
        port.open()
        uart = ParallelUart(port)
        uart.request = 90000
        result["before_fw"] = fw()
        result["before_zero"] = require_owner_service(uart.query("ZERO STATUS"))
        result["before_capture"] = require_completed(uart.raw_query("ADC PAR STATUS"))
        active = prefix.with_suffix(".active-code.bin")
        cli("-u", hex(BASES[slot]), hex(len(image)), active)
        verify_active_code(active.read_bytes(), image, slot)
        result["active_code_verified"] = True
        # Exactly one reset, only after every identity/output gate above passed.
        result["reset_commands"] = 1
        cli("-rst")
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            try:
                result["after_fw"] = fw()
                break
            except TimeoutError:
                pass  # Read-only status polling; never repeat the reset.
        else:
            raise TimeoutError("Confirmed diagnostic did not return; no reset retry")
        result["after_service"] = require_fresh_owner(uart)
        result["after_hardware"] = hardware()
        result["pass"] = True
        print(f"OWNER RESTART PASS: {slot}, GEN={generation}, one reset, outputs locked", flush=True)
    except BaseException as error:
        result["failure"] = str(error)
        raise
    finally:
        result["sample_commands"] = uart.sample_commands if uart else 0
        result["uart"] = uart.lines if uart else []
        if port is not None:
            port.close()
        prefix.with_suffix(".json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print("Evidence: " + str(prefix.with_suffix(".json")), flush=True)


if __name__ == "__main__":
    main()
