"""Deploy locked same-group ADC1/2 diagnostic to inactive A via official UART IAP.

Exact confirmed PA1-only B is preserved. No sample/motor command, direct
metadata write or forced confirmation. Drive 12 V must be physically off.
"""
import hashlib
import adc_parallel_acceptance as parallel
import adc_pa1_only_acceptance as fallback
import adc_sampletime_acceptance as old_a
from adc_owner_acceptance import require_owner_service
from adc12_only_report import require_status
from firmware_transfer_iap import ROOT, image_info
from zero_async_clock_acceptance import locked_baseline

PROFILE = "ADC12_ONLY_SAMPLE247_20261010"
OUTPUT = ROOT / "safety_backups/adc12-only-live-20261010"
PINNED = {"A": "a936a0fb74604e65b56a37f81a1870b625bf90900068429f065f8e42cf17ed1a",
          "B": fallback.PINNED["B"]}


def pinned_image(slot):
    if slot == "B":
        return fallback.pinned_image(slot)
    if slot != "A":
        raise ValueError("Only APP A/B identities exist")
    path = ROOT / "foc2_app_a/build/Adc12Only20261010/foc2.bin"
    image = path.read_bytes()
    if (image_info(image)[0] != "A" or hashlib.sha256(image).hexdigest() != PINNED["A"] or
            b"MODE=ADC12_ONLY CAPTURE_MASK=3 CH=2 REAL_W=0 PAD_W=ZERO_UNSAMPLED" not in image or
            b"SMP_CYCLES=247.5 SMP_CHECK=" not in image):
        raise RuntimeError("Exact offline-verified ADC1/2-only A required")
    return path, image


def diagnostic_baseline(data):
    baseline = locked_baseline(data, known={"A": frozenset((old_a.PINNED["A"], PINNED["A"])),
                                         "B": frozenset((PINNED["B"],))})
    if baseline["current"] != "B" or baseline["images"]["B"]["sha256"] != PINNED["B"]:
        raise RuntimeError("Only exact confirmed single-ADC B may stage inactive A")
    return baseline


def require_fresh_adc12(uart):
    zero = require_owner_service(uart.query("ZERO STATUS"))
    raw = require_status(uart.raw_query("ADC PAR STATUS"))
    for key, value in (("STATE", "0"), ("REASON", "0"), ("CEN", "0"),
                       ("NU", "0"), ("NV", "0"), ("NW", "0"), ("IRQ", "0,0,0"),
                       ("ERR", "0,0,0"), ("SMP_CHECK", "0")):
        if raw.get(key) != value:
            raise RuntimeError("Fresh unsampled ADC1/2 profile required: " + key)
    return {"zero": zero, "raw": raw}


def main():
    parallel.main(image_provider=pinned_image, baseline_checker=diagnostic_baseline,
                  fresh_checker=require_fresh_adc12, image_hashes=PINNED,
                  output_dir=OUTPUT, profile=PROFILE)


if __name__ == "__main__": main()
