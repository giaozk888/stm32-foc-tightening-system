"""One bounded unfiltered injected zero check after exact locked A deployment.

No reset, reflash, retry, calibration publication to motor offsets, or output
unlock. The MCU owns the 5 second acquisition limit and first failure latch.
"""
import zero_async_clock_sample as shared
from zero_injected_control_acceptance import (
    OUTPUT, PINNED, PROFILE, PATH_ADDRESSES, require_injected_registers,
    require_fresh_owner,
)


def require_handover(record):
    # Keep the legacy exact handover validator unchanged for older profiles.
    if (record.get("profile") != PROFILE or record.get("target_slot") != "A" or
            record.get("image_sha256") != PINNED["A"] or
            record.get("physical_drive_off_user_confirmed") is not True or
            record.get("force_confirm") is not False or
            record.get("direct_metadata_write") is not False):
        raise RuntimeError("Exact normally deployed injected A fixture required")
    require_fresh_owner("1 OK ZERO " + " ".join(f"{k}={v}" for k, v in
                        record.get("three_phase_service", {}).get("zero", {}).items()))
    regs = record.get("async_clock_registers", {})
    require_injected_registers("\n".join(f"{a} : {v}" for a, v in regs.items()))
    return shared.require_handover(record, image_hashes=PINNED)


def main():
    shared.main(handover_checker=require_handover, image_hashes=PINNED,
                output_dir=OUTPUT, clock_addresses=PATH_ADDRESSES,
                clock_checker=require_injected_registers,
                fresh_checker=require_fresh_owner, sample_label="INJECTED CONTROL-PATH ZERO")


if __name__ == "__main__":
    main()
