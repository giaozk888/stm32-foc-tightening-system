"""One authorized dual-ground batch of exact GPIO-low A; no reset or motor action."""
import argparse
from functools import partial
import math
import sys
import adc_parallel_sample as parallel
from adc_owner_acceptance import require_owner_service
from adc_owner_sample import deployment_identity as owner_identity
from adc_reference_sample import ReferenceUart
from adc_reference_report import require_supply, analyze
from adc_control_pins_low_acceptance import (
    PINNED, PROFILE, OUTPUT, require_fresh_low, require_status, verify_capture,
)

def deployment_identity(evidence):
    slot, generation = owner_identity(evidence, image_hashes=PINNED, profile=PROFILE)
    raw = evidence.get("three_phase_service", {}).get("raw", {})
    if slot != "A" or any(raw.get(k) != v for k, v in (
            ("MODE", "ADC12_REFERENCE"), ("PIN_POLICY", "GPIO_LOW"), ("PIN_CFG", "1"),
            ("PIN_LEVEL", "1"), ("CAPTURE_MASK", "3"), ("REAL_W", "0"),
            ("PAD_W", "ZERO_UNSAMPLED"), ("SUPPLY_POLICY", "EXPLICIT_OFF_ON"),
            ("POWER", "NONE"), ("ADMIT_MV", "0"), ("SMP_CYCLES", "247.5"), ("SMP_CHECK", "0"))):
        raise RuntimeError("Fresh normally deployed exact GPIO-low A required")
    return slot, generation


def single_control_description(control):
    if control not in ("UL", "VL", "WL"):
        raise ValueError("Only one lower control wire may be selected")
    others = ",".join(s for s in ("UH", "VH", "WH", "UL", "VL", "WL") if s != control)
    return f"ONLY {control} disconnected and loose end insulated; {others} connected; common ground unchanged"

def main():
    parser = argparse.ArgumentParser(add_help=False)
    power = parser.add_mutually_exclusive_group(required=True)
    power.add_argument("--power-on", action="store_true")
    power.add_argument("--power-off", action="store_true")
    parser.add_argument("--both-ground-confirmed", action="store_true")
    wiring = parser.add_mutually_exclusive_group()
    wiring.add_argument("--upper-three-disconnected", action="store_true",
                        help="Record user-confirmed UH/VH/WH disconnected, UL/VL/WL connected; not a GPIO inference")
    wiring.add_argument("--lower-three-disconnected", action="store_true",
                        help="Record user-confirmed UL/VL/WL disconnected, UH/VH/WH connected; not a GPIO inference")
    wiring.add_argument("--all-six-connected", action="store_true",
                        help="Record user-confirmed all six control wires connected; not a GPIO inference")
    wiring.add_argument("--only-disconnected-control", choices=("UL", "VL", "WL"))
    parser.add_argument("--pa0-measured-volts", type=float, required=True)
    parser.add_argument("--pa1-measured-volts", type=float, required=True)
    args, remaining = parser.parse_known_args()
    values = (args.pa0_measured_volts, args.pa1_measured_volts)
    if not args.both_ground_confirmed or not all(math.isfinite(v) and abs(v) <= .05 for v in values):
        parser.error("Both MCU-ground inputs, driver IU/IV disconnected, measured within 0.05 V required")
    state = "ON" if args.power_on else "OFF"
    mapping = {
        "U": f"PA0/ADC1 through about 1 kohm to MCU GND; IU/IV disconnected; prior user measurement {values[0]:g} V under unchanged ground wiring",
        "V": f"PA1/ADC2 through about 1 kohm to MCU GND; IU/IV disconnected; prior user measurement {values[1]:g} V under unchanged ground wiring",
        "W": "UNSAMPLED zero padding; not a third current channel"}
    if args.upper_three_disconnected:
        mapping["CONTROL_WIRING_USER_CONFIRMED"] = (
            "UH/VH/WH disconnected and loose ends insulated; UL/VL/WL connected; common ground unchanged")
    elif args.lower_three_disconnected:
        mapping["CONTROL_WIRING_USER_CONFIRMED"] = (
            "UL/VL/WL disconnected and loose ends insulated; UH/VH/WH connected; common ground unchanged")
    elif args.all_six_connected:
        mapping["CONTROL_WIRING_USER_CONFIRMED"] = (
            "UH/VH/WH connected; UL/VL/WL connected; common ground unchanged")
    elif args.only_disconnected_control:
        mapping["CONTROL_WIRING_USER_CONFIRMED"] = single_control_description(args.only_disconnected_control)
    sys.argv = [sys.argv[0], *remaining]
    parallel.main(
        deployment_checker=deployment_identity, fresh_checker=require_fresh_low,
        service_checker=require_owner_service, image_hashes=PINNED, output_dir=OUTPUT,
        status_checker=partial(require_status, power=state),
        capture_verifier=partial(verify_capture, power=state), capture_analyzer=analyze,
        capture_label="ADC12 BOTH_GROUND GPIO_LOW " + state +
                      (" UPPER_DISCONNECTED" if args.upper_three_disconnected else
                       " LOWER_DISCONNECTED" if args.lower_three_disconnected else
                       " ALL_CONNECTED" if args.all_six_connected else
                       " ONLY_" + args.only_disconnected_control + "_DISCONNECTED" if args.only_disconnected_control else ""), quiet_acquisition=True,
        uart_factory=ReferenceUart, supply_checker=partial(require_supply, power=state),
        sample_command="ADC PAR SAMPLE " + state, supply_state=state,
        raw_mapping=mapping,
        csv_headers=("index", "nominal_trigger_time_us_not_measured", "PA0_GROUNDED_RAW",
                     "PA1_GROUNDED_RAW", "W_UNSAMPLED_PADDING"))

if __name__ == "__main__": main()
