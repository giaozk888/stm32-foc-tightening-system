"""Deploy known-input-only hard-off B; preserve exact confirmed ADC1/2 A."""
import hashlib
import adc_parallel_acceptance as parallel
import adc12_only_acceptance as fallback
from adc_owner_acceptance import require_owner_service
from adc_reference_report import require_status
from firmware_transfer_iap import ROOT, image_info
from zero_async_clock_acceptance import locked_baseline

PROFILE = "ADC12_REFERENCE_INPUT_20261010"
OUTPUT = ROOT / "safety_backups/adc-reference-input-live-20261010"
PINNED = {"A": fallback.PINNED["A"],
          "B": "6cb151fa8b3d8150381e9ee4c028b0b9e7f16b41777a19ea25c493c96e977f21"}


def pinned_image(slot):
    if slot == "A":
        return fallback.pinned_image(slot)
    if slot != "B":
        raise ValueError("Only APP A/B identities exist")
    path = ROOT / "foc2_app_b/build/AdcReference20261010/foc2.bin"
    image = path.read_bytes()
    if (image_info(image)[0] != "B" or hashlib.sha256(image).hexdigest() != PINNED["B"] or
            b"MODE=ADC12_REFERENCE CAPTURE_MASK=3 CH=2 REAL_W=0 PAD_W=ZERO_UNSAMPLED" not in image or
            b"SUPPLY_POLICY=EXPLICIT_OFF_ON POWER=%s ADMIT_MV=%lu" not in image or
            b"ADC3PAR_REFERENCE_REQUIRES_12V_OFF" not in image or
            b"ADC3PAR_REFERENCE_REQUIRES_12V_ON" not in image):
        raise RuntimeError("Exact offline-verified locked reference-input B required")
    return path, image


def diagnostic_baseline(data):
    baseline = locked_baseline(data, known={"A": frozenset((PINNED["A"],)),
                                         "B": frozenset((fallback.PINNED["B"], PINNED["B"]))})
    if baseline["current"] != "A" or baseline["images"]["A"]["sha256"] != PINNED["A"]:
        raise RuntimeError("Only exact confirmed locked A may stage inactive B")
    return baseline


def require_fresh_reference(uart):
    zero = require_owner_service(uart.query("ZERO STATUS"))
    raw = require_status(uart.raw_query("ADC PAR STATUS"), power="NONE")
    for key, value in (("STATE", "0"), ("REASON", "0"), ("CEN", "0"),
                       ("NU", "0"), ("NV", "0"), ("NW", "0"), ("IRQ", "0,0,0"),
                       ("ERR", "0,0,0"), ("SMP_CHECK", "0"), ("ADMIT_MV", "0")):
        if raw.get(key) != value:
            raise RuntimeError("Fresh unsampled known-reference profile required: " + key)
    return {"zero": zero, "raw": raw}


def main():
    parallel.main(image_provider=pinned_image, baseline_checker=diagnostic_baseline,
                  fresh_checker=require_fresh_reference, image_hashes=PINNED,
                  output_dir=OUTPUT, profile=PROFILE)


if __name__ == "__main__": main()
