"""Read-only SWD verification of a completed raw ADC DMA capture.

Verifies the running public image, derives the raw-buffer location from its
ELF, and compares all 8192 ADC values with the existing UART export. Does not
reset, halt, write target memory, start acquisition, or change any setting.
"""
import argparse
import hashlib
import json
import re
import struct
import subprocess
import time
import zlib
from pathlib import Path

from adc_dma_raw_acceptance import OUTPUT, PINNED, pinned_image
from adc_dma_raw_sample import RawUart, require_status
from zero_async_clock_acceptance import CLI, SN, ADDRESSES
from zero_span100_acceptance import BASES, require_registers
from zero_retest_deploy import require_confirmed, require_service


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--capture", type=Path, required=True)
    args = parser.parse_args()
    capture = json.loads(args.capture.read_text(encoding="utf-8"))
    slot = capture["after_fw"]["CURRENT"]
    if (slot not in PINNED or capture.get("capture_pass") is not True
            or capture.get("sha256") != PINNED[slot] or len(capture.get("pairs", [])) != 4096):
        raise RuntimeError("A completed pinned raw ADC capture is required")
    image_path, image = pinned_image(slot)
    elf = image_path.with_suffix(".elf")
    nm = Path(r"D:\software\arm\bin\arm-none-eabi-nm.exe")
    symbols = subprocess.run([str(nm), "-S", "-a", str(elf)], check=True,
                             capture_output=True, text=True).stdout
    matches = re.findall(r"(?m)^([0-9a-fA-F]+) ([0-9a-fA-F]+) b raw$", symbols)
    if len(matches) != 1:
        raise RuntimeError("Raw-array ELF symbol is not unique")
    address, size = map(lambda x: int(x, 16), matches[0])
    if size != 16384 or address < 0x20000000 or address + size > 0x2001FFC0:
        raise RuntimeError("Unexpected ADC array layout")
    OUTPUT.mkdir(parents=True, exist_ok=True)
    prefix = OUTPUT / f"readback-{time.time_ns()}"
    result = {"pass": False, "capture": str(args.capture), "slot": slot,
              "reset": False, "halt": False, "flash_write": False, "target_ram_write": False,
              "sample_commands": 0, "steps": [], "raw_address": hex(address), "bytes": size}
    port = uart = None

    def cli(*arguments):
        p = subprocess.run([CLI, "-c", "port=SWD", "mode=HOTPLUG", "freq=1000", "sn=" + SN,
                            *map(str, arguments)], capture_output=True, text=True,
                           errors="replace", timeout=30)
        output = p.stdout + p.stderr
        result["steps"].append({"args": list(map(str, arguments)), "code": p.returncode, "output": output})
        if p.returncode or "Error:" in output:
            raise RuntimeError("Read-only SWD operation failed")
        return output

    def hardware():
        arguments = []
        for a in ADDRESSES:
            arguments.extend(("-r32", hex(a), "4"))
        return require_registers(cli(*arguments), slot)

    def status():
        fw = require_confirmed(uart.query("FW STATUS", 3), slot)
        if fw["GEN"] != capture["after_fw"]["GEN"]:
            raise RuntimeError("Firmware generation changed after capture")
        zero = require_service(uart.query("ZERO STATUS"))
        dma = require_status(uart.raw_query("ADC DMA STATUS"), terminal=True)
        if dma.get("CRC") != capture["crc32"]:
            raise RuntimeError("The completed buffer no longer belongs to this capture")
        return {"fw": fw, "zero": zero, "dma": dma}

    try:
        result["before_hardware"] = hardware()
        import serial
        port = serial.Serial(port=None, baudrate=115200, timeout=.02, write_timeout=1)
        port.dtr = port.rts = False
        port.port = "COM5"
        port.open()
        uart = RawUart(port)
        result["before_status"] = status()
        active = prefix.with_suffix(".active-code.bin")
        cli("-u", hex(BASES[slot]), hex(len(image)), active)
        if active.read_bytes() != image:
            raise RuntimeError("Active code does not match the ELF-associated pinned image")
        result["image_sha256"] = hashlib.sha256(image).hexdigest()
        raw_path = prefix.with_suffix(".raw.bin")
        cli("-u", hex(address), hex(size), raw_path)
        raw = raw_path.read_bytes()
        if len(raw) != size:
            raise RuntimeError("Incomplete SRAM capture")
        values = struct.unpack("<8192H", raw)
        pairs = list(zip(values[:4096], values[4096:]))
        mismatch = [i for i, pair in enumerate(pairs) if list(pair) != capture["pairs"][i]]
        result["mismatched_pairs"] = len(mismatch)
        result["first_mismatches"] = mismatch[:16]
        result["raw_sha256"] = hashlib.sha256(raw).hexdigest()
        packed = b"".join(struct.pack("<HH", *pair) for pair in pairs)
        result["crc32"] = f"{zlib.crc32(packed):08X}"
        if mismatch or result["crc32"] != capture["crc32"]:
            raise RuntimeError("SRAM values differ from the UART capture")
        result["after_status"] = status()
        result["after_hardware"] = hardware()
        result["pass"] = True
        print(f"SWD RAW READBACK PASS: 4096 pairs match UART exactly; CRC={result['crc32']}; outputs locked")
    except BaseException as error:
        result["failure"] = str(error)
        raise
    finally:
        if port is not None:
            port.close()
        result["uart"] = uart.lines if uart else []
        prefix.with_suffix(".json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print("Evidence: " + str(prefix.with_suffix(".json")), flush=True)


if __name__ == "__main__":
    main()
