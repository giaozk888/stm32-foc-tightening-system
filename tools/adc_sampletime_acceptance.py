"""Deploy only inactive A: 247.5-cycle, hard-off parallel ADC-owner contrast.

Keep the exact confirmed 12.5-cycle B fallback intact. The reviewed UART
pw_transfer engine handles staging and normal trial/confirmation. No samples,
motor commands, direct metadata writes or forced confirmation here.
"""
import hashlib

import adc_owner_acceptance as owner
import adc_parallel_acceptance as parallel
from adc_parallel_report import require_status
from firmware_transfer_iap import ROOT, image_info
from zero_async_clock_acceptance import locked_baseline

PROFILE = "ADC_OWNER_SAMPLE247_20261010"
OUTPUT = ROOT / "safety_backups/adc-sample247-live-20261010"
# B is intentionally the unchanged old fallback, not a second long-sample image.
PINNED = {
    "A": "badda0cf03feba864e844309bd331ba5d9acba5c3ad98db36739d3a0e0f4ff44",
    "B": owner.PINNED["B"],
}
KNOWN = {slot: owner.KNOWN[slot] | {PINNED[slot]} for slot in "AB"}


def pinned_image(slot):
    if slot == "B":
        return owner.pinned_image(slot)
    if slot != "A":
        raise ValueError("Only APP A/B identities exist")
    path = ROOT / "foc2_app_a/build/AdcSample24720261010/foc2.bin"
    image = path.read_bytes()
    if (image_info(image)[0] != "A" or hashlib.sha256(image).hexdigest() != PINNED["A"] or
            b"SMP_CYCLES=247.5 SMP_CHECK=" not in image):
        raise RuntimeError("Exact offline-verified long-sampling diagnostic A required")
    return path, image


def diagnostic_baseline(data):
    baseline = locked_baseline(data, known=KNOWN)
    if (baseline["current"] != "B" or
            baseline["images"]["B"]["sha256"] != owner.PINNED["B"]):
        raise RuntimeError("Only confirmed exact 12.5-cycle B may stage inactive A")
    return baseline


def require_long_status(line, terminal=False):
    row = require_status(line, terminal=terminal)
    if row.get("SMP_CYCLES") != "247.5":
        raise RuntimeError("247.5-cycle diagnostic identity missing")
    if terminal and row.get("SMP_CHECK") != "7":
        raise RuntimeError("All three actual SMPR settings must have been verified before trigger")
    return row


def require_fresh_long(uart):
    result = owner.require_fresh_owner(uart)
    if (result["raw"].get("SMP_CYCLES") != "247.5" or
            result["raw"].get("SMP_CHECK") != "0"):
        raise RuntimeError("Fresh unsampled 247.5-cycle diagnostic required")
    return result


def main():
    parallel.main(image_provider=pinned_image, baseline_checker=diagnostic_baseline,
                  fresh_checker=require_fresh_long, image_hashes=PINNED,
                  output_dir=OUTPUT, profile=PROFILE)


if __name__ == "__main__":
    main()
