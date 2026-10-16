"""One locked ADC1/2 capture with both inputs on the same known divider.

Only host labels/gates change. Reuses exact image, output, supply, freshness,
CRC and no-retry checks. No reset, flash, motor command or ADC reconfiguration.
"""
import argparse
import math
import sys

import adc_parallel_sample as parallel
from adc12_only_sample import deployment_identity
from adc12_only_acceptance import OUTPUT as ADC12_OUTPUT, PINNED, require_fresh_adc12
from adc12_only_report import require_status, verify_capture, analyze
from adc_owner_acceptance import require_owner_service

OUTPUT = ADC12_OUTPUT.parent / "adc12-equal-input-live-20261010"


def main():
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--same-divider-confirmed", action="store_true")
    parser.add_argument("--pa0-measured-volts", type=float, required=True)
    parser.add_argument("--pa1-measured-volts", type=float, required=True)
    args, remaining = parser.parse_known_args()
    if not args.same_divider_confirmed:
        parser.error("PA0 via about 1 kohm and PA1 must share the same divider; IU/IV disconnected")
    if not all(math.isfinite(v) and 1.4 <= v <= 1.9
               for v in (args.pa0_measured_volts, args.pa1_measured_volts)):
        parser.error("Current measured PA0/PA1 divider voltages required (1.4..1.9 V)")
    sys.argv = [sys.argv[0], *remaining]
    parallel.main(
        deployment_checker=deployment_identity, fresh_checker=require_fresh_adc12,
        service_checker=require_owner_service, image_hashes=PINNED, output_dir=OUTPUT,
        status_checker=require_status, capture_verifier=verify_capture,
        capture_analyzer=analyze, capture_label="ADC12_EQUAL_INPUT", quiet_acquisition=True,
        raw_mapping={
            "U": f"PA0/ADC1_IN1 via about 1 kohm to same divider as PA1; IU/IV disconnected; user measured {args.pa0_measured_volts:g} V to MCU GND",
            "V": f"PA1/ADC2_IN2 same divider node as PA0; IU/IV disconnected; user measured {args.pa1_measured_volts:g} V to MCU GND",
            "W": "UNSAMPLED zero transport padding"},
        csv_headers=("index", "nominal_trigger_time_us_not_measured",
                     "PA0_ADC1_COMMON_DIVIDER_RAW", "PA1_ADC2_COMMON_DIVIDER_RAW",
                     "W_UNSAMPLED_PADDING"))


if __name__ == "__main__":
    main()
