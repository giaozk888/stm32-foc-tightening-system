"""Exact output-locked injected-path zero fixture; never enables FOC/PWM.

Uses current sole-ADC-owner code, not historical pre-owner artifacts. Only
confirmed extended raw B may stage inactive A through official UART Transfer.
The ADC setup is shared with normal control; normal FOC/startup is NOT run.
"""
import hashlib
import re

import adc_parallel_acceptance as deploy
from adc_reference_double_acceptance import PINNED as RAW_PINNED, pinned_image as raw_image
from firmware_transfer_iap import ROOT, image_info
from zero_async_clock_acceptance import locked_baseline, require_async_registers as async_clock
from zero_async_clock_sample import require_fresh_boot
from adc_owner_acceptance import require_owner_service

PROFILE = "ZERO_INJECTED_CONTROL_OFF_20261012"
OUTPUT = ROOT / "safety_backups/zero-injected-control-off-20261012"
PINNED = {"A": "4f0efe0d7ae590f1840da1d7b27b767fedebcdc7ad6fac33ab867e4ec85873cd",
          "B": RAW_PINNED["B"]}
PATH_ADDRESSES = (0x50000308, 0x40021088, 0x40012C28, 0x40012C2C,
                  0x40012C00, 0x40012C04, 0x40012C0C, 0x40012C1C, 0x40012C40,
                  0x50000004, 0x50000008, 0x5000000C, 0x50000014, 0x5000004C,
                  0x50000104, 0x50000108, 0x5000010C, 0x50000114, 0x5000014C,
                  0x48000000, 0x4800000C)


def pinned_image(slot):
    if slot == "B":
        return raw_image(slot)
    if slot != "A":
        raise ValueError("Only inactive A injected fixture is supported")
    path = ROOT / "foc2_app_a/build/ZeroInjectedControlOff20261012/foc2.bin"
    image = path.read_bytes()
    if (image_info(image)[0] != "A" or hashlib.sha256(image).hexdigest() != PINNED["A"] or
            b"ADC_OWNER=1" not in image or b"motor NOT qualified" not in image):
        raise RuntimeError("Exact current output-locked injected A image required")
    return path, image


def diagnostic_baseline(data):
    result = locked_baseline(data, known={"A": frozenset((RAW_PINNED["A"],)),
                                        "B": frozenset((RAW_PINNED["B"],))})
    if result["current"] != "B":
        raise RuntimeError("Only confirmed exact raw B may stage inactive A; never overwrite B")
    return result


def require_injected_registers(output):
    values = {int(a, 16): int(v, 16) for a, v in re.findall(
        r"(?im)^0x([0-9A-F]+)\s*:\s*([0-9A-F]{8})\s*$", output)}
    if set(values) != set(PATH_ADDRESSES):
        raise RuntimeError("Complete injected-path register evidence required")
    async_clock("\n".join(f"0x{a:08X} : {values[a]:08X}" for a in
                          (0x50000308, 0x40021088, 0x40012C28, 0x40012C2C)))
    # CMSIS/LL G474 definitions: CMS=1, MMS2=OC4REF, OC4M=PWM2.
    if (values[0x40012C00] & 0x61 != 0x20 or
            values[0x40012C04] & 0xF00000 != 0x700000 or
            values[0x40012C0C] & 0x11 or
            values[0x40012C1C] & 0x1007000 != 0x7000 or
            values[0x40012C40] != 3500):
        raise RuntimeError("Stopped center-aligned TIM1/CH4 geometry mismatch")
    for base, channel in ((0x50000000, 1), (0x50000100, 2)):
        if (values[base + 0x4C] != ((channel << 9) | 0xA0) or
                (values[base + 0x14] >> (3 * channel)) & 7 != 2 or
                values[base + 0x0C] & ((1 << 25) | 0x19) or
                values[base + 0x08] & 8 != 8):
            raise RuntimeError("IU/IV must be armed independent 12-bit injected, rising TIM1 TRGO2, 12.5 cycles")
    if values[0x50000004] & 0x60 != 0x40 or values[0x50000104] & 0x60:
        raise RuntimeError("Only ADC1 injected sequence IRQ may be enabled")
    if values[0x48000000] & 0xF != 0xF or values[0x4800000C] & 0xF:
        raise RuntimeError("PA0/PA1 must be analog without pulls")
    return {f"0x{a:08X}": f"{v:08X}" for a, v in values.items()}


def require_fresh_owner(line):
    require_owner_service(line)
    return require_fresh_boot(line)


def require_fresh_injected(uart):
    return {"zero": require_fresh_owner(uart.query("ZERO STATUS"))}


def main():
    deploy.main(image_provider=pinned_image, baseline_checker=diagnostic_baseline,
                fresh_checker=require_fresh_injected, image_hashes=PINNED,
                output_dir=OUTPUT, profile=PROFILE, clock_addresses=PATH_ADDRESSES,
                clock_checker=require_injected_registers)


if __name__ == "__main__":
    main()
