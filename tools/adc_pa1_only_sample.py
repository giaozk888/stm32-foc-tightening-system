"""One PA1-only 247.5-cycle raw capture; no reset/write/motor action or retries."""
import adc_parallel_sample as parallel
from adc_owner_acceptance import require_owner_service
from adc_owner_sample import deployment_identity as owner_identity
from adc_pa1_only_acceptance import OUTPUT, PINNED, PROFILE, require_fresh_pa1
from adc_pa1_only_report import require_status, verify_capture, analyze


def deployment_identity(evidence):
    slot, generation = owner_identity(evidence, image_hashes=PINNED, profile=PROFILE)
    raw = evidence.get("three_phase_service", {}).get("raw", {})
    if slot != "B" or any(raw.get(key) != value for key, value in (
            ("MODE", "PA1_ONLY"), ("CAPTURE_MASK", "2"), ("CH", "1"), ("REAL_W", "0"),
            ("PAD_UW", "ZERO_UNSAMPLED"), ("SMP_CYCLES", "247.5"), ("SMP_CHECK", "0"))):
        raise RuntimeError("Only normally deployed fresh PA1-only B admitted")
    return slot, generation


def main():
    parallel.main(deployment_checker=deployment_identity, fresh_checker=require_fresh_pa1,
                  service_checker=require_owner_service, image_hashes=PINNED, output_dir=OUTPUT,
                  status_checker=require_status, capture_verifier=verify_capture,
                  capture_analyzer=analyze, capture_label="PA1_ONLY",
                  raw_mapping={"U": "UNSAMPLED zero transport padding", "V": "PA1/ADC2_IN2 divider reference",
                               "W": "UNSAMPLED zero transport padding"},
                  csv_headers=("index", "nominal_trigger_time_us_not_measured", "U_UNSAMPLED_PADDING",
                               "PA1_ADC2_DIVIDER_RAW", "W_UNSAMPLED_PADDING"))


if __name__ == "__main__":
    main()
