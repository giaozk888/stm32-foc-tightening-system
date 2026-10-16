"""One authorized reset of exact GPIO-low A after preserving its prior batch.

Drive 12 V must be physically off. No sampling, Flash/RAM writes, halt,
motion, retry, or fallback-image changes. Control-wire connection condition
is user-confirmed wiring, not something inferred from GPIO registers.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import time

from adc_control_pins_low_acceptance import (
    OUTPUT, PINNED, pinned_image, require_status, verify_capture,
    require_fresh_low, read_pin_registers,
)
from adc_control_pins_low_sample import deployment_identity
from adc_reference_sample import ReferenceUart
from adc_reference_ground_restart import require_generation
from adc_owner_acceptance import require_owner_service
from adc_parallel_acceptance import CLI, SN, ADDRESSES, require_registers
from zero_span100_acceptance import BASES


def prior_identity(deployment, capture, readback):
    slot, generation = deployment_identity(deployment)
    power = capture.get("requested_supply_state")
    if (slot != "A" or power not in ("ON", "OFF") or
            capture.get("capture_pass") is not True or capture.get("sha256") != PINNED[slot] or
            capture.get("sample_commands") != 1 or capture.get("host_quiet_after_sample_ack") is not True or
            any(capture.get(k) is not False for k in ("reset", "flash_write", "motion_commands", "thresholds_changed")) or
            readback.get("pass") is not True or readback.get("slot") != slot or
            readback.get("image_sha256") != PINNED[slot] or readback.get("mismatched_entries") != 0 or
            readback.get("bytes") != 24576 or readback.get("sample_commands") != 0 or
            any(readback.get(k) is not False for k in ("reset", "halt", "flash_write", "target_ram_write")) or
            readback.get("crc32") != capture.get("crc32")):
        raise RuntimeError("Exact one-shot GPIO-low A and independently preserved RAM batch required")
    for fw in (capture.get("before_fw", {}), capture.get("after_fw", {}),
               readback.get("before_status", {}).get("fw", {}),
               readback.get("after_status", {}).get("fw", {})):
        line = "1 OK FW " + " ".join(f"{k}={v}" for k, v in fw.items())
        require_generation(line, slot, generation)
    triples = capture.get("triples", [])
    lines = [line for line in capture.get("uart", []) if " OK ADC3PAR " in line
             and "STATE=4 " in line and f"CRC={capture.get('crc32')}" in line]
    if not lines:
        raise RuntimeError("Full prior terminal proof missing")
    for line in lines:
        if verify_capture(line, triples, power=power) != capture["crc32"]:
            raise RuntimeError("Prior full-batch CRC mismatch")
    for status in (capture.get("terminal", {}), capture.get("after_status", {}),
                   readback.get("before_status", {}).get("raw", {}),
                   readback.get("after_status", {}).get("raw", {})):
        row = require_status("1 OK ADC3PAR " + " ".join(f"{k}={v}" for k, v in status.items()),
                             terminal=True, power=power)
        if row.get("CRC") != capture["crc32"]:
            raise RuntimeError("Retained prior terminal identity mismatch")
    return slot, generation, capture["crc32"], power


def verify_active_code(code, image):
    if code != image or hashlib.sha256(code).hexdigest() != PINNED["A"]:
        raise RuntimeError("Only exact locked GPIO-low A may be reset")


def main(*, prior_checker=None, code_checker=None, image_provider=None,
         fresh_checker=None, status_checker=None, pin_reader=None,
         output_dir=None, reset_label="GPIO-low A", physical_conditions_basis=None,
         allow_sensor_inputs=False):
    # Defaults retain the original A-only behavior; alternate profiles must
    # explicitly supply their own exact-image, layout and status validators.
    prior_checker = prior_checker or prior_identity
    code_checker = code_checker or verify_active_code
    image_provider = image_provider or pinned_image
    fresh_checker = fresh_checker or require_fresh_low
    status_checker = status_checker or require_status
    pin_reader = pin_reader or read_pin_registers
    output_dir = output_dir or OUTPUT
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("deployment", "capture", "readback"):
        parser.add_argument("--" + name, type=Path, required=True)
    for name in ("allow-one-reset", "drive-12v-off", "motor-leads-disconnected"):
        parser.add_argument("--" + name, action="store_true")
    inputs = parser.add_mutually_exclusive_group()
    inputs.add_argument("--both-ground-confirmed", action="store_true")
    inputs.add_argument("--iu-iv-connected", action="store_true")
    wiring = parser.add_mutually_exclusive_group(required=True)
    wiring.add_argument("--upper-three-disconnected", action="store_true")
    wiring.add_argument("--lower-three-disconnected", action="store_true")
    wiring.add_argument("--all-six-connected", action="store_true")
    wiring.add_argument("--only-disconnected-control", choices=("UL", "VL", "WL"))
    parser.add_argument("--common-ground-replaced", action="store_true")
    args = parser.parse_args()
    if not all((args.allow_one_reset, args.drive_12v_off, args.motor_leads_disconnected,
                args.both_ground_confirmed or (allow_sensor_inputs and args.iu_iv_connected))):
        parser.error("One-reset authorization and unchanged off/ground conditions required")
    if args.iu_iv_connected and not (args.all_six_connected and args.common_ground_replaced):
        parser.error("Sensor input reset requires all six controls and retained replacement ground")
    if args.common_ground_replaced and not args.all_six_connected:
        parser.error("Ground-line replacement contrast requires all six controls connected")
    group = "upper" if args.upper_three_disconnected else "lower" if args.lower_three_disconnected else "all"
    wire_conditions = {"UH_VH_WH": "disconnected" if group == "upper" else "connected",
                       "UL_VL_WL": "disconnected" if group == "lower" else "connected",
                       "common_ground": "unchanged"}
    if args.common_ground_replaced:
        wire_conditions["common_ground"] = "existing inter-board signal GND replaced by a shorter direct wire; user completed instructed change, not independently measured"
    if args.only_disconnected_control:
        wire_conditions.update(
            UH_VH_WH="connected", UL_VL_WL="mixed", disconnected_control=args.only_disconnected_control,
            per_control_wire={s: "disconnected" if s == args.only_disconnected_control else "connected"
                              for s in ("UH", "VH", "WH", "UL", "VL", "WL")})
    slot, generation, prior_crc, prior_power = prior_checker(*[
        json.loads(getattr(args, n).read_text(encoding="utf-8")) for n in ("deployment", "capture", "readback")])
    _, image = image_provider(slot)
    output_dir.mkdir(parents=True, exist_ok=True)
    label = "all-connected" if group == "all" else group + "-disconnected"
    if args.only_disconnected_control:
        label = "only-" + args.only_disconnected_control.lower() + "-disconnected"
    if args.common_ground_replaced:
        label = "all-connected-ground-replaced"
    if args.iu_iv_connected:
        label += "-iu-iv"
    prefix = output_dir / f"{label}-reset-{time.time_ns()}"
    result = {"pass": False, "reset_commands": 0, "sample_commands": 0,
              "reset_user_authorized": True, "drive_12v_off_user_confirmed": True,
              "motor_leads_disconnected_user_confirmed": True, "both_ground_user_confirmed": args.both_ground_confirmed,
              "wiring_user_confirmed": wire_conditions,
              "physical_conditions_basis": "Explicit in-context user confirmation of power off and group wiring",
              "flash_write": False, "target_ram_write": False, "halt": False,
              "motion_commands": False, "thresholds_changed": False, "supply_admission_changed": False,
              "deployment": str(args.deployment), "prior_capture": str(args.capture),
              "prior_readback": str(args.readback), "steps": []}
    result.update(slot=slot, generation=generation, prior_crc=prior_crc)
    if args.iu_iv_connected:
        result["input_wiring_user_basis"] = "IU->PA0, IV->PA1; diagnostic grounding resistors removed per instruction; in-context wiring completion, not independently measured"
    if physical_conditions_basis is not None:
        result["physical_conditions_basis"] = physical_conditions_basis
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
        code_checker(path.read_bytes(), image)
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
        result["before_pins"] = pin_reader()
        result["before_image_sha256"] = code_check(".before-code.bin")
        port, uart = console()
        result["before_fw"] = require_generation(uart.query("FW STATUS", 3), slot, generation)
        result["before_zero"] = require_owner_service(uart.query("ZERO STATUS"))
        raw = status_checker(uart.raw_query("ADC PAR STATUS"), terminal=True, power=prior_power)
        if raw.get("CRC") != prior_crc:
            raise RuntimeError("Prior RAM capture changed; no reset")
        result["before_raw"] = raw
        result["before_uart"] = uart.lines
        port.close()
        port = None
        # Count before issuing: uncertain acknowledgement must never cause retry.
        result["reset_commands"] = 1
        cli("-rst")
        print(f"One {reset_label} reset issued; wait 25 s; no SAMPLE or Flash.", flush=True)
        time.sleep(25)
        port, uart = console()
        result["after_fw"] = require_generation(uart.query("FW STATUS", 5), slot, generation)
        result["fresh_service"] = fresh_checker(uart)
        result["after_uart"] = uart.lines
        port.close()
        port = None
        result["after_hardware"] = hardware()
        result["after_pins"] = pin_reader()
        result["after_image_sha256"] = code_check(".after-code.bin")
        result["pass"] = True
        print(f"{label.upper()} RESET PASS: same confirmed {slot}, GEN={generation}, fresh unsampled, outputs locked.", flush=True)
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
