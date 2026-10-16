"""Known-input ADC1/2 contrast; one capture, no reset/flash/motor commands.

PA0 must be disconnected from the driver and connected through about 1 kohm
to MCU GND. PA1 retains the approximately 1.6 V divider. Reuses all pinned
identity/output/supply/freshness/no-retry gates of the existing sampler.
"""
import argparse
import sys

import adc_parallel_sample as parallel
from adc12_only_sample import deployment_identity
from adc12_only_acceptance import OUTPUT as ADC12_OUTPUT, PINNED, require_fresh_adc12
from adc12_only_report import require_status, verify_capture, analyze
from adc_owner_acceptance import require_owner_service

OUTPUT = ADC12_OUTPUT.parent / "adc12-ground-live-20261010"


def main():
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--pa0-ground-pa1-divider-confirmed", action="store_true")
    parser.add_argument("--quiet-acquisition", action="store_true",
                        help="No host polling for 0.5 s after SAMPLE ACK; MCU traffic is not suppressed")
    args, remaining = parser.parse_known_args()
    if not args.pa0_ground_pa1_divider_confirmed:
        parser.error("Explicit current PA0-ground/PA1-divider wiring confirmation required")
    sys.argv = [sys.argv[0], *remaining]
    parallel.main(
        deployment_checker=deployment_identity, fresh_checker=require_fresh_adc12,
        service_checker=require_owner_service, image_hashes=PINNED,
        output_dir=OUTPUT.parent / "adc12-ground-quiet-live-20261010" if args.quiet_acquisition else OUTPUT,
        status_checker=require_status, capture_verifier=verify_capture,
        capture_analyzer=analyze, capture_label="ADC12_GROUND_DIVIDER",
        quiet_acquisition=args.quiet_acquisition,
        raw_mapping={"U": "PA0/ADC1_IN1 through about 1 kohm to MCU GND; IVU disconnected; user-confirmed",
                     "V": "PA1/ADC2_IN2 approx 1.6 V divider reference; user-confirmed",
                     "W": "UNSAMPLED zero transport padding"},
        csv_headers=("index", "nominal_trigger_time_us_not_measured",
                     "PA0_ADC1_GROUNDED_RAW", "PA1_ADC2_DIVIDER_RAW", "W_UNSAMPLED_PADDING"))


if __name__ == "__main__":
    main()
