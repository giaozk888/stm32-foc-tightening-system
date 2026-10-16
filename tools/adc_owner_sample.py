"""One finite raw acquisition of the exact confirmed ADC-owner parallel profile.

Shares the no-retry sampler, with stronger new-image and owner identity gates.
No Flash writes, resets, motor commands or zero/torque qualification.
"""
import adc_parallel_sample as parallel
from adc_owner_acceptance import (
    OUTPUT, PINNED, PROFILE, require_fresh_owner, require_owner_service,
)


def deployment_identity(evidence, *, image_hashes=PINNED, profile=PROFILE):
    slot = evidence.get("target_slot")
    if (slot not in image_hashes or evidence.get("profile") != profile or
            evidence.get("pass") is not True or evidence.get("inspect_only") is not False or
            evidence.get("image_sha256") != image_hashes[slot] or
            not evidence.get("final_flash", {}).get("all_protected_regions_unchanged") or
            evidence.get("motion_commands") is not False or
            evidence.get("sampling_commands") is not False or
            evidence.get("force_confirm") is not False or
            evidence.get("direct_metadata_write") is not False or
            evidence.get("physical_drive_off_user_confirmed") is not True or
            evidence.get("three_phase_service", {}).get("zero", {}).get("ADC_OWNER") != "1"):
        raise RuntimeError("Exact normally deployed ADC-owner parallel profile required")
    fw = evidence.get("final_fw", {})
    if (fw.get("CURRENT") != slot or fw.get("CONFIRMED") != slot or
            fw.get("PENDING") != "-" or fw.get("ATTEMPTS") != "0" or fw.get("ACTIVE") != "0" or
            not str(fw.get("GEN", "")).isdigit()):
        raise RuntimeError("Confirmed ADC-owner deployment generation missing")
    return slot, fw["GEN"]


def main():
    parallel.main(deployment_checker=deployment_identity, fresh_checker=require_fresh_owner,
                  service_checker=require_owner_service, image_hashes=PINNED, output_dir=OUTPUT)


if __name__ == "__main__":
    main()
