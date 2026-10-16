"""One off-supply reset of the exact B/8192 diagnostic after full saved audit.

Never samples, halts, writes Flash/RAM or retries a reset. Default reset
implementation retains all physical and output-lock admission checks.
"""
import hashlib
import json
from pathlib import Path
import struct
import adc_control_pins_low_restart as shared
from adc_reference_double_acceptance import (
    OUTPUT, PINNED, pinned_image, require_fresh_double, read_pin_registers,
)
from adc_reference_double_sample import deployment_identity
from adc_reference_double_report import require_status, verify_capture
from adc_reference_ground_restart import require_generation


def prior_identity(deployment, capture, readback):
    slot, generation = deployment_identity(deployment)
    power = capture.get("requested_supply_state")
    if (slot != "B" or power not in ("ON", "OFF") or
            capture.get("capture_pass") is not True or capture.get("sha256") != PINNED[slot] or
            capture.get("sample_commands") != 1 or capture.get("host_quiet_after_sample_ack") is not True or
            any(capture.get(k) is not False for k in ("reset", "flash_write", "motion_commands", "thresholds_changed")) or
            readback.get("pass") is not True or readback.get("slot") != slot or
            readback.get("image_sha256") != PINNED[slot] or readback.get("mismatched_entries") != 0 or
            readback.get("bytes") != 32768 or readback.get("sample_commands") != 0 or
            any(readback.get(k) is not False for k in ("reset", "halt", "flash_write", "target_ram_write")) or
            readback.get("crc32") != capture.get("crc32")):
        raise RuntimeError("Exact one-shot B/8192 capture and full independent readback required")
    for fw in (capture.get("before_fw", {}), capture.get("after_fw", {}),
               readback.get("before_status", {}).get("fw", {}),
               readback.get("after_status", {}).get("fw", {})):
        require_generation("1 OK FW " + " ".join(f"{k}={v}" for k,v in fw.items()), slot, generation)
    lines = [line for line in capture.get("uart", []) if " OK ADC3PAR " in line
             and "STATE=4 " in line and f"CRC={capture.get('crc32')}" in line]
    if not lines:
        raise RuntimeError("Prior terminal UART proof missing")
    for line in lines:
        verify_capture(line, capture.get("triples", []), power=power)
    for raw in (capture.get("terminal", {}), capture.get("after_status", {}),
                readback.get("before_status", {}).get("raw", {}),
                readback.get("after_status", {}).get("raw", {})):
        verify_capture("1 OK ADC3PAR " + " ".join(f"{k}={v}" for k,v in raw.items()),
                       capture["triples"], power=power)
    return slot, generation, capture["crc32"], power


def verify_active_code(code, image):
    if code != image or hashlib.sha256(code).hexdigest() != PINNED["B"]:
        raise RuntimeError("Only exact GPIO-low extended B may be reset")


def audit_saved_files(capture_path, readback_path):
    capture = json.loads(capture_path.read_text(encoding="utf-8"))
    readback = json.loads(readback_path.read_text(encoding="utf-8"))
    if Path(readback.get("capture", "")).resolve() != capture_path.resolve():
        raise RuntimeError("Readback refers to a different capture")
    verify_active_code(readback_path.with_suffix(".active-code.bin").read_bytes(), pinned_image("B")[1])
    raw = readback_path.with_suffix(".raw.bin").read_bytes()
    if len(raw) != 32768 or hashlib.sha256(raw).hexdigest() != readback.get("raw_sha256"):
        raise RuntimeError("Saved RAM length/hash mismatch")
    values = struct.unpack("<16384H", raw)
    triples = [[values[i], values[8192+i], 0] for i in range(8192)]
    if triples != capture.get("triples"):
        raise RuntimeError("Saved RAM differs from complete UART batch")


def main():
    # Preflight the saved binary evidence before any hardware access. Shared
    # argparse subsequently enforces all required reset/wiring/off flags.
    import argparse
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--capture", type=Path, required=True)
    parser.add_argument("--readback", type=Path, required=True)
    parser.add_argument("--common-ground-replaced", action="store_true")
    parser.add_argument("--iu-iv-connected", action="store_true")
    args, _ = parser.parse_known_args()
    audit_saved_files(args.capture, args.readback)
    if args.iu_iv_connected and not args.common_ground_replaced:
        parser.error("IU/IV diagnostic requires retained replacement common ground")
    basis = ("User replied wiring completed after instructions to keep 12 V off, reconnect WL and "
             "replace only the inter-board signal ground; six controls connected; PA0/PA1 ground resistors "
             "and disconnected motor leads inherited unchanged. Physical completion inferred in context, "
             "not independently measured" if args.common_ground_replaced else
             "User explicitly replied drive 12 V off after the reset instruction; latest unplug statement "
             "interpreted in context as WL; other five controls, both grounded inputs and disconnected "
             "motor leads inherited unchanged, not independently measured")
    if args.iu_iv_connected:
        basis = ("User replied wiring complete for IU->PA0 and IV->PA1, then explicitly drive 12 V off; "
                 "grounding resistors removed per instruction; six controls, replacement common GND and "
                 "disconnected motor leads inherited unchanged. No independent electrical measurement.")
    shared.main(prior_checker=prior_identity, code_checker=verify_active_code,
                image_provider=pinned_image, fresh_checker=require_fresh_double,
                status_checker=require_status, pin_reader=read_pin_registers,
                output_dir=OUTPUT, reset_label="GPIO-low extended B",
                physical_conditions_basis=basis, allow_sensor_inputs=args.iu_iv_connected)


if __name__ == "__main__":
    main()
