"""One finite ADC1/2-only capture, locked outputs; no reset, write or motor command."""
import adc_parallel_sample as parallel
from adc_owner_acceptance import require_owner_service
from adc_owner_sample import deployment_identity as owner_identity
from adc12_only_acceptance import OUTPUT, PINNED, PROFILE, require_fresh_adc12
from adc12_only_report import require_status, verify_capture, analyze


def deployment_identity(evidence):
    slot, generation = owner_identity(evidence, image_hashes=PINNED, profile=PROFILE)
    raw = evidence.get("three_phase_service", {}).get("raw", {})
    if slot != "A" or any(raw.get(key) != value for key, value in (
            ("MODE", "ADC12_ONLY"), ("CAPTURE_MASK", "3"), ("CH", "2"), ("REAL_W", "0"),
            ("PAD_W", "ZERO_UNSAMPLED"), ("SMP_CYCLES", "247.5"), ("SMP_CHECK", "0"))):
        raise RuntimeError("Only normally deployed fresh ADC1/2-only A admitted")
    return slot, generation


def main():
    parallel.main(deployment_checker=deployment_identity, fresh_checker=require_fresh_adc12,
                  service_checker=require_owner_service, image_hashes=PINNED, output_dir=OUTPUT,
                  status_checker=require_status, capture_verifier=verify_capture,
                  capture_analyzer=analyze, capture_label="ADC12_ONLY",
                  raw_mapping={"U": "PA0/ADC1_IN1 unchanged diagnostic input; not qualified current",
                               "V": "PA1/ADC2_IN2 divider reference",
                               "W": "UNSAMPLED zero transport padding"},
                  csv_headers=("index", "nominal_trigger_time_us_not_measured", "PA0_ADC1_RAW",
                               "PA1_ADC2_DIVIDER_RAW", "W_UNSAMPLED_PADDING"))


if __name__ == "__main__": main()
