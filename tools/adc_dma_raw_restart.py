"""Restart a verified, confirmed, output-locked ADC DMA diagnostic once.

Used for a user-requested new capture after a wiring correction. Checks the
active image against the pinned public binary before resetting, preserves the
deployment generation, and never flashes or starts sampling. No reset retries.
"""
import argparse
import hashlib
import json
import subprocess
import time
from pathlib import Path

from adc_dma_raw_acceptance import OUTPUT, PINNED, pinned_image
from adc_dma_raw_sample import RawUart, require_status
from zero_async_clock_acceptance import CLI, SN, ADDRESSES, CLOCK_ADDRESSES, require_async_registers
from zero_span100_acceptance import BASES, require_registers
from zero_retest_deploy import require_confirmed, require_service


def require_idle(row):
    if row.get("CEN") != "0" or row.get("REASON") != "0" or row.get("STATE") not in ("0", "4"):
        raise RuntimeError("Diagnostic must be fresh or successfully completed, with timer stopped")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--deployment-evidence", type=Path, required=True)
    parser.add_argument("--allow-one-reset", action="store_true")
    parser.add_argument("--motor-leads-disconnected", action="store_true")
    parser.add_argument("--supply-12v-0p5a-no-alarm", action="store_true")
    parser.add_argument("--reason", default="user-requested retest after IU wiring correction")
    args = parser.parse_args()
    if not all((args.allow_one_reset, args.motor_leads_disconnected, args.supply_12v_0p5a_no_alarm)):
        parser.error("Explicit new-capture reset permission and confirmed physical conditions required")
    evidence = json.loads(args.deployment_evidence.read_text(encoding="utf-8"))
    slot = evidence.get("target_slot")
    if (slot not in PINNED or evidence.get("pass") is not True or evidence.get("inspect_only") is not False
            or evidence.get("image_sha256") != PINNED[slot]
            or not evidence.get("final_flash", {}).get("all_protected_regions_unchanged")):
        raise RuntimeError("Successful pinned diagnostic deployment evidence required")
    _, image = pinned_image(slot)
    generation = evidence["final_fw"]["GEN"]
    OUTPUT.mkdir(parents=True, exist_ok=True)
    prefix = OUTPUT / f"restart-{time.time_ns()}"
    result = {"pass": False, "reset_requested": False, "reset_commands": 0,
              "flash_write": False, "sample_commands": 0, "motion_commands": False,
              "slot": slot, "image_sha256": PINNED[slot], "steps": [],
              "reason": args.reason}
    port = None
    uart = None

    def cli(*arguments):
        p = subprocess.run([CLI, "-c", "port=SWD", "mode=HOTPLUG", "freq=1000", "sn=" + SN,
                            *map(str, arguments)], capture_output=True, text=True,
                           errors="replace", timeout=30)
        output = p.stdout + p.stderr
        result["steps"].append({"args": list(map(str, arguments)), "code": p.returncode, "output": output})
        if p.returncode or "Error:" in output:
            raise RuntimeError("SWD check/reset did not complete; no automatic retry")
        return output

    def hardware():
        values = []
        for address in ADDRESSES:
            values.extend(("-r32", hex(address), "4"))
        outputs = require_registers(cli(*values), slot)
        values = []
        for address in CLOCK_ADDRESSES:
            values.extend(("-r32", hex(address), "4"))
        return {"outputs": outputs, "clock": require_async_registers(cli(*values))}

    def fw():
        row = require_confirmed(uart.query("FW STATUS", 1), slot)
        if row.get("GEN") != generation:
            raise RuntimeError("Deployment generation changed")
        return row

    try:
        result["before_hardware"] = hardware()
        import serial
        port = serial.Serial(port=None, baudrate=115200, timeout=.02, write_timeout=1)
        port.dtr = port.rts = False
        port.port = "COM5"
        port.open()
        uart = RawUart(port)
        result["before_fw"] = fw()
        result["before_zero"] = require_service(uart.query("ZERO STATUS"))
        before = require_status(uart.raw_query("ADC DMA STATUS"))
        require_idle(before)
        result["before_dma"] = before
        active = prefix.with_suffix(".active-code.bin")
        cli("-u", hex(BASES[slot]), hex(len(image)), active)
        code = active.read_bytes()
        if code != image or hashlib.sha256(code).hexdigest() != PINNED[slot]:
            raise RuntimeError("Active firmware is not the exact pinned locked diagnostic")
        result["active_code_verified"] = True
        if before["STATE"] == "4":
            result["reset_requested"] = True
            result["reset_commands"] = 1
            cli("-rst")
            deadline = time.monotonic() + 8
            while True:
                try:
                    result["after_fw"] = fw()
                    break
                except TimeoutError:
                    if time.monotonic() >= deadline:
                        raise
        else:
            result["after_fw"] = fw()
        result["after_zero"] = require_service(uart.query("ZERO STATUS"))
        if result["after_zero"].get("ADC_READY") != "1" or result["after_zero"].get("STATE") != "0":
            raise RuntimeError("Fresh ADC diagnostic is not ready")
        result["after_dma"] = require_status(uart.raw_query("ADC DMA STATUS"))
        require_idle(result["after_dma"])
        if result["after_dma"]["STATE"] != "0":
            raise RuntimeError("ADC DMA capture has not returned to fresh state")
        result["after_hardware"] = hardware()
        result["pass"] = True
        print(f"RESTART PASS: confirmed {slot}, GEN={generation}, reset commands={result['reset_commands']}, outputs locked")
    except BaseException as error:
        result["failure"] = str(error)
        raise
    finally:
        result["uart"] = uart.lines if uart else []
        if port is not None:
            port.close()
        prefix.with_suffix(".json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print("Evidence: " + str(prefix.with_suffix(".json")), flush=True)


if __name__ == "__main__":
    main()
