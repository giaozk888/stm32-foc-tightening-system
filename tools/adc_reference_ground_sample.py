"""One truthful dual-ground capture of the pinned hard-off reference B.

No firmware changes, reset, protection relaxation or repeated SAMPLE. Both
PA0/PA1 must be disconnected from driver outputs and grounded at MCU GND.
Supply admission remains the unchanged, explicit OFF/ON firmware policy.
"""
import argparse
from functools import partial
import math
import sys

import adc_parallel_sample as parallel
from adc_owner_acceptance import require_owner_service
from adc_reference_acceptance import OUTPUT as REFERENCE_OUTPUT, PINNED, require_fresh_reference
from adc_reference_sample import ReferenceUart, deployment_identity
from adc_reference_report import require_status, require_supply, verify_capture, analyze

OUTPUT = REFERENCE_OUTPUT.parent / "adc-reference-ground-live-20261011"


def main():
    parser = argparse.ArgumentParser(add_help=False)
    power = parser.add_mutually_exclusive_group(required=True)
    power.add_argument("--power-off", action="store_true")
    power.add_argument("--power-on", action="store_true")
    parser.add_argument("--both-ground-confirmed", action="store_true")
    parser.add_argument("--pa0-measured-volts", type=float, required=True)
    parser.add_argument("--pa1-measured-volts", type=float, required=True)
    args, remaining = parser.parse_known_args()
    values = (args.pa0_measured_volts, args.pa1_measured_volts)
    if not args.both_ground_confirmed or not all(math.isfinite(v) and abs(v) <= .05 for v in values):
        parser.error("Both MCU-ground inputs, driver signals disconnected, measured within 0.05 V required")
    state = "OFF" if args.power_off else "ON"
    sys.argv = [sys.argv[0], *remaining]
    parallel.main(
        deployment_checker=deployment_identity, fresh_checker=require_fresh_reference,
        service_checker=require_owner_service, image_hashes=PINNED, output_dir=OUTPUT,
        status_checker=partial(require_status, power=state),
        capture_verifier=partial(verify_capture, power=state), capture_analyzer=analyze,
        capture_label="ADC12 REFERENCE BOTH_GROUND " + state, quiet_acquisition=True,
        uart_factory=ReferenceUart, supply_checker=partial(require_supply, power=state),
        sample_command="ADC PAR SAMPLE " + state, supply_state=state,
        raw_mapping={
            "U": f"PA0/ADC1_IN1 through about 1 kohm to labeled MCU GND; driver IU/IV disconnected; user measured {values[0]:g} V",
            "V": f"PA1/ADC2_IN2 through about 1 kohm to labeled MCU GND; driver IU/IV disconnected; user measured {values[1]:g} V",
            "W": "UNSAMPLED zero padding; not a third current channel"},
        csv_headers=("index", "nominal_trigger_time_us_not_measured",
                     "PA0_ADC1_GROUNDED_RAW", "PA1_ADC2_GROUNDED_RAW", "W_UNSAMPLED_PADDING"))


if __name__ == "__main__":
    main()
