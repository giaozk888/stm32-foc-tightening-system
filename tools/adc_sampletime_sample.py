"""One finite output-locked 247.5-cycle contrast capture; never reset or move a motor.

Use only the exact normally deployed A evidence. Require the three-ADC SMPR
readback mask, unchanged generation, full raw CRC and independent output locks.
Physical sensor supply is confirmed separately after the power-off deployment.
"""
import adc_owner_sample as owner_sample
import adc_parallel_sample as parallel
from adc_owner_acceptance import require_owner_service
from adc_sampletime_acceptance import (
    OUTPUT, PINNED, PROFILE, require_fresh_long, require_long_status,
)


def deployment_identity(evidence):
    slot, generation = owner_sample.deployment_identity(
        evidence, image_hashes=PINNED, profile=PROFILE)
    raw = evidence.get("three_phase_service", {}).get("raw", {})
    if slot != "A" or raw.get("SMP_CYCLES") != "247.5" or raw.get("SMP_CHECK") != "0":
        raise RuntimeError("Only the fresh long-sampling A deployment is eligible")
    return slot, generation


def main():
    parallel.main(deployment_checker=deployment_identity, fresh_checker=require_fresh_long,
                  service_checker=require_owner_service, image_hashes=PINNED,
                  output_dir=OUTPUT, status_checker=require_long_status)


if __name__ == "__main__":
    main()
