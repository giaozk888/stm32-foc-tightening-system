"""Read-only final Flash/UART/SWD proof after a failed normal B trial.

No reset, sampling, motion, fault clear, parameter write or Flash write.
Requires the earlier verified stage record; checks exact locked A fallback.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import time

from bounded_speed_stage import OUTPUT, baseline
from firmware_transfer_iap import fields
from zero_retest_deploy import CLI, SN, DiagnosticUart, latest_meta, require_confirmed, require_service
from zero_span100_acceptance import ADDRESSES, require_registers


def compare_final(before, actual, image, stage_generation):
    initial = baseline(before)
    final = baseline(actual)
    if initial["generation"] != stage_generation or final["generation"] <= stage_generation:
        raise RuntimeError("Unexpected final/baseline generation")
    for name, start, end in (
        ("bootloader", 0, 0x8000), ("A", 0x8000, 0x40000),
        ("KVS_reserved", 0x78000, 0x7E800), ("parameters", 0x7F800, 0x80000),
    ):
        if before[start:end] != actual[start:end]:
            raise RuntimeError("Protected region changed: " + name)
    if actual[0x40000:0x40000 + len(image)] != image:
        raise RuntimeError("Staged B code changed unexpectedly")
    old, new = latest_meta(before), latest_meta(actual)
    if new[6:8] != old[6:8] or new[8:10] != (0, 0):
        raise RuntimeError("Fallback A metadata changed or failed B trial not retired")
    return {"all_protected_regions_unchanged": True, "b_code_unchanged": True,
            "failed_b_retired": True, "current": "A", "generation": final["generation"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage-record", type=Path, required=True)
    args = parser.parse_args()
    record_path = args.stage_record.resolve()
    if record_path.parent != OUTPUT.resolve() or not record_path.name.startswith("stage-"):
        parser.error("Use a stage record from this bounded test directory")
    stage = json.loads(record_path.read_text(encoding="utf-8"))
    if stage.get("stage_pass") is not True or stage.get("reset") is not False:
        raise RuntimeError("Earlier verified stage-only evidence required")
    run_id = record_path.stem.removeprefix("stage-")
    before_path = OUTPUT / "private-flash" / f"{run_id}-before.bin"
    image = Path(stage["image"]).read_bytes()
    if hashlib.sha256(image).hexdigest() != stage["image_sha256"]:
        raise RuntimeError("Public image changed after staging")
    result_path = OUTPUT / f"postflight-{time.time_ns()}.json"
    actual_path = OUTPUT / "private-flash" / f"{run_id}-final.bin"
    if actual_path.exists():
        raise RuntimeError("Preserve existing readback; choose the original evidence")
    result = {"readback_pass": False, "motion_commands": 0, "reset": False,
              "flash_write": False, "sampling": False, "stage_record": str(record_path), "steps": []}
    port = uart = None

    def cli(*arguments):
        p = subprocess.run([CLI, "-c", "port=SWD", "mode=HOTPLUG", "freq=1000", "sn=" + SN,
                            *map(str, arguments)], capture_output=True, text=True,
                           errors="replace", timeout=30)
        output = p.stdout + p.stderr
        result["steps"].append({"args": list(map(str, arguments)), "code": p.returncode, "output": output})
        if p.returncode or "Error:" in output:
            raise RuntimeError("Read-only SWD failed")
        return output

    def registers():
        arguments = []
        for address in ADDRESSES:
            arguments.extend(("-r32", hex(address), "4"))
        return require_registers(cli(*arguments), "A")

    try:
        before = before_path.read_bytes()
        result["before_registers"] = registers()
        import serial
        port = serial.Serial(port=None, baudrate=115200, timeout=.02, write_timeout=1)
        port.dtr = port.rts = False
        port.port = "COM5"
        port.open()
        uart = DiagnosticUart(port)
        result["fw"] = require_confirmed(uart.query("FW STATUS", 3), "A")
        result["zero"] = require_service(uart.query("ZERO STATUS"))
        result["safe"] = fields(uart.query("ANALOG SAFE STATUS"))
        result["status"] = fields(uart.query("STATUS"))
        cli("-u", "0x08000000", "0x80000", actual_path)
        result["flash"] = compare_final(before, actual_path.read_bytes(), image, stage["baseline"]["generation"])
        if int(result["fw"]["GEN"]) != result["flash"]["generation"]:
            raise RuntimeError("UART/Flash metadata generation differs")
        result["after_registers"] = registers()
        require_confirmed(uart.query("FW STATUS"), "A")
        require_service(uart.query("ZERO STATUS"))
        result["readback_pass"] = True
        print("FINAL READBACK PASS: confirmed hard-off A; failed B retired; "
              "bootloader/A/data unchanged; NO RESET OR START", flush=True)
    except BaseException as error:
        result["failure"] = str(error)
        raise
    finally:
        if port is not None:
            port.close()
        result["uart"] = uart.lines if uart else []
        result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print("Evidence: " + str(result_path), flush=True)


if __name__ == "__main__":
    main()
