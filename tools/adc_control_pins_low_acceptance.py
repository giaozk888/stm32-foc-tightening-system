"""Deploy ONLY inactive A GPIO-low diagnostic; preserve exact locked reference B.

No motor commands, sampling, direct SWD programming, or forced confirmation.
Drive 12 V must physically be off for --allow-deploy.
"""
import hashlib
import re
import subprocess
import adc_parallel_acceptance as parallel
from adc_reference_acceptance import PINNED as REFERENCE_PINNED, pinned_image as reference_image
from adc_reference_acceptance import require_fresh_reference
from adc_reference_report import require_status as reference_status, verify_capture as reference_verify
from firmware_transfer_iap import ROOT, image_info
from zero_async_clock_acceptance import locked_baseline

PROFILE = "ADC12_REFERENCE_GPIO_LOW_20261011"
OUTPUT = ROOT / "safety_backups/adc-control-pins-low-live-20261011"
PINNED = {"A": "2af9cd54af2ae799763ef960a27dce76fefcdf4aaa3d78e2ae77dd707b221dc2",
          "B": REFERENCE_PINNED["B"]}
PIN_ADDRESSES = tuple(base + off for base in (0x48000400, 0x48000800)
                      for off in (0, 4, 8, 12, 16, 20)) + (0x40012C00, 0x40012C20, 0x40012C44, 0xE000ED08)

def pinned_image(slot):
    if slot == "B": return reference_image(slot)
    if slot != "A": raise ValueError("Only APP A/B")
    path = ROOT / "foc2_app_a/build/AdcPinsLow20261011/foc2.bin"
    image = path.read_bytes()
    if (image_info(image)[0] != "A" or hashlib.sha256(image).hexdigest() != PINNED["A"] or
            b"PIN_POLICY=GPIO_LOW PIN_CFG=%u PIN_LEVEL=%u" not in image or
            b"MODE=ADC12_REFERENCE CAPTURE_MASK=3 CH=2 REAL_W=0 PAD_W=ZERO_UNSAMPLED" not in image or
            b"SUPPLY_POLICY=EXPLICIT_OFF_ON POWER=%s ADMIT_MV=%lu" not in image):
        raise RuntimeError("Exact offline-verified GPIO-low locked A required")
    return path, image

def diagnostic_baseline(data):
    baseline = locked_baseline(data, known={s: frozenset((REFERENCE_PINNED[s],)) for s in "AB"})
    if baseline["current"] != "B":
        raise RuntimeError("Only confirmed reference B may stage inactive GPIO-low A")
    return baseline

def require_status(line, terminal=False, power=None):
    row = reference_status(line, terminal=terminal, power=power)
    if any(row.get(k) != v for k, v in (("PIN_POLICY", "GPIO_LOW"), ("PIN_CFG", "1"), ("PIN_LEVEL", "1"))):
        raise ValueError("Six GPIO push-pull low controls required")
    return row

def verify_capture(line, triples, power=None):
    require_status(line, terminal=True, power=power)
    return reference_verify(line, triples, power=power)

def require_pin_registers(output, slot="A"):
    values = {int(a, 16): int(v, 16) for a, v in
              re.findall(r"(?im)^0x([0-9A-F]+)\s*:\s*([0-9A-F]{8})\s*$", output)}
    if set(values) != set(PIN_ADDRESSES) or slot != "A" or values[0xE000ED08] != 0x08008000:
        raise RuntimeError("Complete GPIO-low A register snapshot required")
    for base, pins, mode_mask, output_mode in ((0x48000400, 0x2003, 0x0c00000f, 0x04000005),
                                             (0x48000800, 7, 0x3f, 0x15)):
        if (values[base] & mode_mask != output_mode or values[base + 4] & pins or
                values[base + 8] & mode_mask or values[base + 12] & mode_mask or
                values[base + 16] & pins or values[base + 20] & pins):
            raise RuntimeError("Control pins not actual low-speed GPIO push-pull low")
    if (values[0x48000814] & (1 << 6) or values[0x40012C00] & 1 or
            values[0x40012C20] or values[0x40012C44] & ((1 << 15) | (1 << 14))):
        raise RuntimeError("SD/timer output lock lost")
    return {f"0x{a:08X}": f"{v:08X}" for a, v in values.items()}

def read_pin_registers():
    args = []
    for a in PIN_ADDRESSES: args.extend(("-r32", hex(a), "4"))
    p = subprocess.run([parallel.CLI, "-c", "port=SWD", "mode=HOTPLUG", "freq=1000",
                        "sn=" + parallel.SN, *args], capture_output=True, text=True, errors="replace", timeout=30)
    output = p.stdout + p.stderr
    if p.returncode or "Error:" in output: raise RuntimeError("Read-only GPIO check failed; no retry")
    return {"registers": require_pin_registers(output), "args": args, "output": output,
            "reset": False, "halt": False, "register_write": False}

def require_fresh_low(uart):
    fresh = require_fresh_reference(uart)
    require_status(uart.raw_query("ADC PAR STATUS"), power="NONE")
    fresh["pin_hardware"] = read_pin_registers()
    return fresh

def main():
    parallel.main(image_provider=pinned_image, baseline_checker=diagnostic_baseline,
                  fresh_checker=require_fresh_low, image_hashes=PINNED, output_dir=OUTPUT, profile=PROFILE)

if __name__ == "__main__": main()
