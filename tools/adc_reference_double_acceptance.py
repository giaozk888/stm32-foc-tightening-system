"""Pinned extended locked B deployment; preserves exact confirmed GPIO-low A.

No sample, motion, forced confirmation or direct metadata write. Drive 12 V
must physically be off before --allow-deploy. Inspection is read-only.
"""
import hashlib
import re
import subprocess
import adc_parallel_acceptance as parallel
import adc_control_pins_low_acceptance as fallback
from adc_reference_acceptance import PINNED as ORIGINAL_REFERENCE
from adc_reference_double_report import require_status
from adc_owner_acceptance import require_owner_service
from firmware_transfer_iap import ROOT, image_info
from zero_async_clock_acceptance import locked_baseline
from zero_span100_acceptance import BASES

PROFILE = "ADC12_REFERENCE_GPIO_LOW_DOUBLE_20261011"
OUTPUT = ROOT / "safety_backups/adc-reference-double-live-20261011"
PINNED = {"A": fallback.PINNED["A"],
          "B": "c42bcd840b40438818dab4124c511750e902ce1ef65a263c08470d6ae8f48e24"}


def pinned_image(slot):
    if slot == "A": return fallback.pinned_image(slot)
    if slot != "B": raise ValueError("Only A/B")
    path = ROOT / "foc2_app_b/build/AdcPinsLowDouble20261011/foc2.bin"
    image = path.read_bytes()
    if (image_info(image)[0] != slot or hashlib.sha256(image).hexdigest() != PINNED[slot] or
            any(s not in image for s in (b"WINDOW=DOUBLE RAW_STORAGE=UV_ONLY",
                b"PIN_POLICY=GPIO_LOW PIN_CFG=%u PIN_LEVEL=%u", b"PAD_W=ZERO_UNSAMPLED"))):
        raise RuntimeError("Exact offline-tested extended locked B required")
    return path, image


def diagnostic_baseline(data):
    known = {"A": frozenset((PINNED["A"],)), "B": frozenset((ORIGINAL_REFERENCE["B"],))}
    result = locked_baseline(data, known=known)
    if result["current"] != "A":
        raise RuntimeError("Only exact confirmed GPIO-low A may stage extended inactive B")
    return result


def require_pin_registers(output, slot="B"):
    values = {int(a, 16): int(v, 16) for a, v in
              re.findall(r"(?im)^0x([0-9A-F]+)\s*:\s*([0-9A-F]{8})\s*$", output)}
    if slot not in BASES or set(values) != set(fallback.PIN_ADDRESSES) or values[0xE000ED08] != BASES[slot]:
        raise RuntimeError("Complete GPIO-low expected-slot register snapshot required")
    for base, pins, mask, mode in ((0x48000400, 0x2003, 0x0c00000f, 0x04000005),
                                   (0x48000800, 7, 0x3f, 0x15)):
        if (values[base] & mask != mode or values[base+4] & pins or values[base+8] & mask or
                values[base+12] & mask or values[base+16] & pins or values[base+20] & pins):
            raise RuntimeError("Six control pins not actual low-speed GPIO push-pull low")
    if (values[0x48000814] & (1 << 6) or values[0x40012C00] & 1 or values[0x40012C20] or
            values[0x40012C44] & ((1 << 15) | (1 << 14))):
        raise RuntimeError("Output lock lost")
    return {f"0x{a:08X}": f"{v:08X}" for a, v in values.items()}


def read_pin_registers():
    args = []
    for a in fallback.PIN_ADDRESSES: args.extend(("-r32", hex(a), "4"))
    p = subprocess.run([parallel.CLI, "-c", "port=SWD", "mode=HOTPLUG", "freq=1000",
                        "sn="+parallel.SN, *args], capture_output=True, text=True, errors="replace", timeout=30)
    output = p.stdout+p.stderr
    if p.returncode or "Error:" in output: raise RuntimeError("Read-only GPIO check failed; no retry")
    return {"registers": require_pin_registers(output), "args": args, "output": output,
            "reset": False, "halt": False, "register_write": False}


def require_fresh_double(uart):
    zero = require_owner_service(uart.query("ZERO STATUS"))
    raw = require_status(uart.raw_query("ADC PAR STATUS"), power="NONE")
    for k, v in (("STATE", "0"), ("REASON", "0"), ("CEN", "0"), ("NU", "0"), ("NV", "0"),
                 ("NW", "0"), ("IRQ", "0,0,0"), ("ERR", "0,0,0"), ("SMP_CHECK", "0"), ("ADMIT_MV", "0")):
        if raw.get(k) != v: raise RuntimeError("Fresh extended unsampled state required: "+k)
    return {"zero": zero, "raw": raw, "pin_hardware": read_pin_registers()}


def main():
    parallel.main(image_provider=pinned_image, baseline_checker=diagnostic_baseline,
                  fresh_checker=require_fresh_double, image_hashes=PINNED, output_dir=OUTPUT, profile=PROFILE)


if __name__ == "__main__": main()
