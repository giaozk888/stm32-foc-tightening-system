"""Deploy inactive B PA1-only diagnostics; preserve exact confirmed long-sample A.

Use the existing guarded official UART IAP. No samples, motor commands,
direct metadata writes or forced confirmation. Defaults are read-only gates.
"""
import hashlib
import adc_parallel_acceptance as parallel
import adc_sampletime_acceptance as fallback
import adc_owner_acceptance as owner
from adc_pa1_only_report import require_status
from firmware_transfer_iap import ROOT, image_info
from zero_async_clock_acceptance import locked_baseline

PROFILE = "ADC_PA1_ONLY_SAMPLE247_20261010"
OUTPUT = ROOT / "safety_backups/adc-pa1-only-live-20261010"
PINNED = {"A": fallback.PINNED["A"],
          "B": "f9b5349f727e6667b0f130fae088d16f8f631ee2b3cbb4457b63d7b41d3e30dd"}


def pinned_image(slot):
    if slot == "A":
        return fallback.pinned_image(slot)
    if slot != "B":
        raise ValueError("Only APP A/B identities exist")
    path = ROOT / "foc2_app_b/build/AdcPa1Only20261010/foc2.bin"
    image = path.read_bytes()
    if (image_info(image)[0] != "B" or hashlib.sha256(image).hexdigest() != PINNED["B"] or
            b"MODE=PA1_ONLY CAPTURE_MASK=2 CH=1 REAL_W=0 PAD_UW=ZERO_UNSAMPLED" not in image or
            b"SMP_CYCLES=247.5 SMP_CHECK=" not in image):
        raise RuntimeError("Exact offline-verified PA1-only diagnostic B required")
    return path, image


def diagnostic_baseline(data):
    baseline = locked_baseline(data, known={"A": frozenset((PINNED["A"],)),
                                         "B": frozenset((owner.PINNED["B"], PINNED["B"]))})
    if baseline["current"] != "A" or baseline["images"]["A"]["sha256"] != PINNED["A"]:
        raise RuntimeError("Only exact confirmed long-sample A may stage inactive B")
    return baseline


def require_fresh_pa1(uart):
    zero = owner.require_owner_service(uart.query("ZERO STATUS"))
    raw = require_status(uart.raw_query("ADC PAR STATUS"))
    for key, value in (("STATE", "0"), ("REASON", "0"), ("CEN", "0"),
                       ("NU", "0"), ("NV", "0"), ("NW", "0"), ("IRQ", "0,0,0"),
                       ("ERR", "0,0,0"), ("SMP_CHECK", "0")):
        if raw.get(key) != value:
            raise RuntimeError("Fresh unsampled PA1-only profile required: " + key)
    return {"zero": zero, "raw": raw}


def main():
    parallel.main(image_provider=pinned_image, baseline_checker=diagnostic_baseline,
                  fresh_checker=require_fresh_pa1, image_hashes=PINNED,
                  output_dir=OUTPUT, profile=PROFILE)


if __name__ == "__main__":
    main()
