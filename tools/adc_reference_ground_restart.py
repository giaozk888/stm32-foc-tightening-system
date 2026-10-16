"""One authorized reset of exact locked B before the dual-ground contrast.

Separate from the OFF-to-ON comparison reset: a preserved, independently
verified ON or OFF batch is admissible here. Never samples, writes Flash/RAM,
halts, or retries reset. Drive 12 V must remain physically off. The cached
unpowered-driver VBUS estimate is recorded but is not used to claim power-off
or authorize a sample. Existing firmware/host supply gates are unchanged.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import time

from adc_reference_acceptance import PINNED, pinned_image, require_fresh_reference
from adc_reference_sample import ReferenceUart, deployment_identity
from adc_reference_compare import audit_capture
from adc_reference_report import require_status
from adc_reference_ground_sample import OUTPUT
from adc_owner_acceptance import require_owner_service
from adc_parallel_acceptance import CLI, SN, ADDRESSES, require_registers
from zero_retest_deploy import require_confirmed
from zero_retest_sample import fields
from zero_span100_acceptance import BASES


def prior_identity(deployment, capture, readback):
    slot, generation = deployment_identity(deployment)
    power = capture.get("requested_supply_state")
    if power not in ("OFF", "ON"):
        raise RuntimeError("Prior batch must record an actual explicit supply admission")
    audit = audit_capture(capture, readback, power)
    if (slot != "B" or audit["generation"] != generation or
            any(readback.get(k) is not False for k in ("reset", "halt", "flash_write", "target_ram_write")) or
            readback.get("sample_commands") != 0):
        raise RuntimeError("Exact deployed B and read-only independent prior-batch verification required")
    return slot, generation, audit["crc32"], power


def verify_active_code(code, image):
    if code != image or hashlib.sha256(code).hexdigest() != PINNED["B"]:
        raise RuntimeError("Only exact hard-off reference B may be reset")


def require_generation(line, slot, generation):
    fw = require_confirmed(line, slot)
    if fw.get("GEN") != generation:
        raise RuntimeError("Generation changed; no reset/retry")
    return fw


def require_prior_status(line, crc, power):
    raw = require_status(line, terminal=True, power=power)
    if raw.get("CRC") != crc:
        raise RuntimeError("Prior capture changed; do not discard it by resetting")
    return raw


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("deployment", "capture", "readback"):
        parser.add_argument("--" + name, type=Path, required=True)
    for name in ("allow-one-reset", "drive-12v-off", "motor-leads-disconnected", "both-ground-confirmed"):
        parser.add_argument("--" + name, action="store_true")
    args = parser.parse_args()
    if not all((args.allow_one_reset, args.drive_12v_off, args.motor_leads_disconnected, args.both_ground_confirmed)):
        parser.error("One-reset authorization and unchanged off/disconnected/both-ground conditions required")
    slot, generation, prior_crc, prior_power = prior_identity(*[
        json.loads(getattr(args, n).read_text(encoding="utf-8")) for n in ("deployment", "capture", "readback")])
    _, image = pinned_image(slot)
    OUTPUT.mkdir(parents=True, exist_ok=True)
    prefix = OUTPUT / f"ground-reset-{time.time_ns()}"
    result = {
        "pass": False, "reset_commands": 0, "sample_commands": 0,
        "reset_user_authorized": True, "drive_12v_off_user_confirmed": True,
        "motor_leads_disconnected_user_confirmed": True, "both_ground_user_confirmed": True,
        "physical_conditions_basis": "Previously instructed conditions unchanged; in-context user start authorization",
        "flash_write": False, "target_ram_write": False, "halt": False,
        "motion_commands": False, "thresholds_changed": False, "supply_admission_changed": False,
        "deployment": str(args.deployment), "prior_capture": str(args.capture),
        "prior_readback": str(args.readback), "steps": []}
    port = uart = None

    def cli(*arguments):
        p = subprocess.run([CLI, "-c", "port=SWD", "mode=HOTPLUG", "freq=1000", "sn=" + SN,
                            *map(str, arguments)], capture_output=True, text=True, errors="replace", timeout=30)
        output = p.stdout + p.stderr
        result["steps"].append({"args": list(map(str, arguments)), "code": p.returncode, "output": output})
        if p.returncode or "Error:" in output:
            raise RuntimeError("SWD check/reset failed; never retry reset")
        return output

    def hardware():
        arguments = []
        for address in ADDRESSES:
            arguments.extend(("-r32", hex(address), "4"))
        return require_registers(cli(*arguments), slot)

    def code_check(suffix):
        path = prefix.with_suffix(suffix)
        cli("-u", hex(BASES[slot]), hex(len(image)), path)
        verify_active_code(path.read_bytes(), image)
        return hashlib.sha256(image).hexdigest()

    def console():
        import serial
        p = serial.Serial(port=None, baudrate=115200, timeout=.02, write_timeout=1)
        p.dtr = p.rts = False
        p.port = "COM5"
        p.open()
        return p, ReferenceUart(p)

    try:
        result["before_hardware"] = hardware()
        result["before_image_sha256"] = code_check(".before-code.bin")
        port, uart = console()
        result["before_fw"] = require_generation(uart.query("FW STATUS", 3), slot, generation)
        result["before_zero"] = require_owner_service(uart.query("ZERO STATUS"))
        result["before_raw"] = require_prior_status(uart.raw_query("ADC PAR STATUS"), prior_crc, prior_power)
        result["cached_supply_estimate_not_off_admission"] = fields(uart.query("ANALOG VOLT"))
        result["before_uart"] = uart.lines
        port.close()
        port = None
        # Exact locked code + hardware + generation + preserved prior CRC above.
        # Set the count before calling: uncertain ACK never causes a second reset.
        result["reset_commands"] = 1
        cli("-rst")
        print("One hard-off reference reset issued; wait 25 s; no SAMPLE or Flash.", flush=True)
        time.sleep(25)
        port, uart = console()
        result["after_fw"] = require_generation(uart.query("FW STATUS", 5), slot, generation)
        result["fresh_service"] = require_fresh_reference(uart)
        result["after_uart"] = uart.lines
        port.close()
        port = None
        result["after_hardware"] = hardware()
        result["after_image_sha256"] = code_check(".after-code.bin")
        result["pass"] = True
        print(f"GROUND RESET PASS: same confirmed {slot}, GEN={generation}, fresh unsampled, outputs locked.", flush=True)
    except BaseException as error:
        result["failure"] = str(error)
        raise
    finally:
        if port is not None:
            port.close()
        result["last_uart"] = uart.lines if uart else []
        result["sample_commands"] = uart.sample_commands if uart else 0
        prefix.with_suffix(".json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print("Evidence: " + str(prefix.with_suffix(".json")), flush=True)


if __name__ == "__main__":
    main()
