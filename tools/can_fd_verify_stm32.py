"""Read-only SWD proof: confirmed B, power off, unchanged A/boot/parameters."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import zlib

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.can_fd_restore_original_slot import latest_meta


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    parser.add_argument("--image", required=True, type=Path)
    args = parser.parse_args()
    for path in (args.baseline, args.output, args.report):
        if not path.resolve().is_relative_to((ROOT / "safety_backups").resolve()):
            parser.error("Private captures and evidence must stay inside safety_backups")
    if args.output.exists() or args.report.exists() or not args.output.parent.is_dir():
        parser.error("Use fresh output/report and an already access-restricted output directory")
    base = args.baseline.read_bytes()
    image = args.image.read_bytes()
    assert len(base) == 0x80000
    cli_path = r"D:\software\cubeprogrammer\bin\STM32_Programmer_CLI.exe"
    def cli(*parameters):
        process = subprocess.run([cli_path, "-c", "port=SWD", "mode=HOTPLUG", "freq=1000",
            "sn=0050003B3235511537333439", *map(str, parameters)],
            text=True, capture_output=True, timeout=30)
        output = process.stdout + process.stderr
        if process.returncode or "Error:" in output:
            raise RuntimeError(output)
        return output
    cli("-u", "0x08000000", "0x80000", args.output)
    captured = args.output.read_bytes()
    assert len(captured) == len(base)
    for start, end in ((0, 0x40000), (0x78000, 0x7e800), (0x7f800, 0x80000)):
        assert captured[start:end] == base[start:end], f"Protected Flash region changed: {start:x}..{end:x}"
    meta = latest_meta(captured)
    assert meta[2:5] == (2, 0, 0), "Not normally confirmed B"
    assert meta[8:10] == (len(image), zlib.crc32(image))
    assert captured[0x40000:0x40000+len(image)] == image, "B image readback differs"
    values = {}
    for name, address in (("vtor", 0xe000ed08), ("cfsr", 0xe000ed28),
                          ("gpio_sd", 0x48000814), ("tim1_bdtr", 0x40012c44)):
        text = cli("-r32", hex(address), "4")
        match = re.search(rf"0x{address:08X}\s*:\s*([0-9A-Fa-f]{{8}})", text, re.I)
        assert match, "SWD register read failed"
        values[name] = int(match[1], 16)
    assert values["vtor"] == 0x08040000 and values["cfsr"] == 0
    assert not values["gpio_sd"] & 0x40 and not values["tim1_bdtr"] & 0x8000
    report = {"pass": True, "read_only": True, "confirmed_slot": "B", "metadata": list(meta),
              "b_size": len(image), "b_sha256": hashlib.sha256(image).hexdigest(),
              "protected_regions_equal": True, "registers": values, "power_stage_enabled": False}
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print("STM32 READBACK PASS: confirmed B, exact image, original A/boot/parameters unchanged, CFSR=0 SD=0 MOE=0")


if __name__ == "__main__":
    main()
