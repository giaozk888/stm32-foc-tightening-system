"""Deploy exact ADC-owner locked diagnostics via the existing official UART IAP.

Requires --allow-deploy --drive-12v-off, or read-only --inspect. Preserve the
entire confirmed fallback and protected regions; never sample or move a motor.
Historical parallel/sequential/raw hashes remain unchanged in their modules.
"""
import hashlib

import adc_parallel_acceptance as parallel
from firmware_transfer_iap import ROOT, image_info
from zero_async_clock_acceptance import locked_baseline
from zero_retest_deploy import require_service

PROFILE = "ADC_OWNER_PARALLEL_20261010"
OUTPUT = ROOT / "safety_backups/adc-owner-live-20261010"
PINNED = {
    "A": "98c1a751981f6470999e6cb9134c6585e9cd99f691dc84c50e0692c7a791c7fb",
    "B": "f532e82dcf457880f489e6da99a7a031582dd04709a3fad74c790fda03b3893c",
}
KNOWN = {slot: frozenset((parallel.OLD_RAW[slot], parallel.SEQUENTIAL_PINNED[slot],
                          parallel.PINNED[slot], PINNED[slot])) for slot in "AB"}


def pinned_image(slot):
    path = ROOT / f"foc2_app_{slot.lower()}/build/AdcOwner20261010/foc2.bin"
    image = path.read_bytes()
    if image_info(image)[0] != slot or hashlib.sha256(image).hexdigest() != PINNED[slot]:
        raise RuntimeError("Exact offline-verified ADC owner image required")
    return path, image


def diagnostic_baseline(data):
    return locked_baseline(data, known=KNOWN)


def require_owner_service(line):
    row = require_service(line)
    if row.get("ADC_OWNER") != "1" or row.get("ADC_READY") != "1":
        raise RuntimeError("ADC sole-owner diagnostic identity missing: " + line)
    return row


def require_fresh_owner(uart):
    result = parallel.require_fresh_parallel(uart)
    if result["zero"].get("ADC_OWNER") != "1":
        raise RuntimeError("Fresh ADC-owner profile required before acquisition")
    return result


def main():
    parallel.main(image_provider=pinned_image, baseline_checker=diagnostic_baseline,
                  fresh_checker=require_fresh_owner, image_hashes=PINNED,
                  output_dir=OUTPUT, profile=PROFILE)


if __name__ == "__main__":
    main()
