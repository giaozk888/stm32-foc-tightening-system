"""One finite three-phase raw capture with outputs locked; never drive a motor.

--inspect is read-only and does not acquire data. A capture requires explicit
one-shot permission and motor U/V/W disconnected, sensor supply 12 V/0.5 A,
no alarm. No reset, Flash write, zero publication or automatic sample retry.
"""
import argparse
import csv
import json
from pathlib import Path
import subprocess
import time

from adc_three_phase_acceptance import (
    OUTPUT, PINNED, ThreePhaseUart, require_fresh_three_phase,
    CLI, SN, ADDRESSES, CLOCK_ADDRESSES, require_registers, require_async_registers,
)
from adc_three_phase_report import CAPACITY, BLOCK, require_status, decode_block, verify_capture, analyze
from zero_retest_deploy import require_confirmed, require_service
from zero_retest_sample import require_supply


def deployment_identity(evidence):
    slot = evidence.get("target_slot")
    if (slot not in PINNED or evidence.get("pass") is not True or
            evidence.get("inspect_only") is not False or
            evidence.get("image_sha256") != PINNED[slot] or
            not evidence.get("final_flash", {}).get("all_protected_regions_unchanged") or
            evidence.get("motion_commands") is not False or
            evidence.get("sampling_commands") is not False):
        raise RuntimeError("Successful exact three-phase locked deployment required")
    fw = evidence.get("final_fw", {})
    if (fw.get("CURRENT") != slot or fw.get("CONFIRMED") != slot or
            fw.get("PENDING") != "-" or fw.get("ATTEMPTS") != "0" or fw.get("ACTIVE") != "0" or
            not str(fw.get("GEN", "")).isdigit()):
        raise RuntimeError("Deployment confirmation/generation missing")
    return slot, fw["GEN"]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--deployment-evidence", type=Path, required=True)
    parser.add_argument("--inspect", action="store_true")
    parser.add_argument("--allow-sample", action="store_true")
    parser.add_argument("--motor-leads-disconnected", action="store_true")
    parser.add_argument("--supply-12v-0p5a-no-alarm", action="store_true")
    args = parser.parse_args()
    if args.inspect == args.allow_sample:
        parser.error("Select read-only inspection OR one explicitly authorized sample")
    if args.allow_sample and not (args.motor_leads_disconnected and args.supply_12v_0p5a_no_alarm):
        parser.error("Current physical conditions required before sampling")
    evidence = json.loads(args.deployment_evidence.read_text(encoding="utf-8"))
    slot, generation = deployment_identity(evidence)
    OUTPUT.mkdir(parents=True, exist_ok=True)
    prefix = OUTPUT / f"capture-{time.time_ns()}"
    result = {"capture_pass": False, "inspection_pass": False, "inspect_only": args.inspect,
              "zero_qualified": False, "motor_qualified": False, "signal_quality_qualified": False,
              "flash_write": False, "reset": False, "motion_commands": False,
              "thresholds_changed": False, "triples": [], "steps": [],
              "deployment_evidence": str(args.deployment_evidence), "sha256": PINNED[slot],
              "motor_leads_disconnected_user_confirmed": args.motor_leads_disconnected,
              "supply_12v_0p5a_no_alarm_user_confirmed": args.supply_12v_0p5a_no_alarm,
              "raw_mapping": {"U": "AMP_IU/PA0/ADC1_IN1", "V": "AMP_IV/PA1/ADC2_IN2",
                              "W": "AMP_IW/PC3/ADC1_IN9 rank2 (sequential)"}}
    port = uart = None

    def hardware():
        def read(addresses):
            command = []
            for address in addresses:
                command.extend(("-r32", hex(address), "4"))
            process = subprocess.run(
                [CLI, "-c", "port=SWD", "mode=HOTPLUG", "freq=1000", "sn=" + SN, *command],
                capture_output=True, text=True, errors="replace", timeout=30)
            output = process.stdout + process.stderr
            result["steps"].append({"args": command, "code": process.returncode, "output": output})
            if process.returncode or "Error:" in output:
                raise RuntimeError("Independent output/clock readback failed")
            return output
        return {"outputs": require_registers(read(ADDRESSES), slot),
                "clock": require_async_registers(read(CLOCK_ADDRESSES))}

    try:
        result["before_hardware"] = hardware()
        import serial
        port = serial.Serial(port=None, baudrate=115200, timeout=.02, write_timeout=1)
        port.dtr = port.rts = False
        port.port = "COM5"
        port.open()
        uart = ThreePhaseUart(port)
        result["before_fw"] = require_confirmed(uart.query("FW STATUS", 3), slot)
        if result["before_fw"]["GEN"] != generation:
            raise RuntimeError("Metadata generation changed after deployment")
        result["before_service"] = require_fresh_three_phase(uart)
        if args.inspect:
            result["inspection_pass"] = True
            print("THREE-PHASE READ-ONLY PASS: fresh locked diagnostic; no sample", flush=True)
            return
        result["supply_estimate"] = require_supply(uart.query("ANALOG VOLT"))
        line = uart.raw_query("ADC 3PH SAMPLE")
        row = require_status(line)
        deadline = time.monotonic() + 3
        while row.get("STATE") not in ("4", "5"):
            if time.monotonic() >= deadline:
                raise TimeoutError("Acquisition deadline exceeded; no repeat/reset")
            time.sleep(.05)
            line = uart.raw_query("ADC 3PH STATUS", timeout=.5)
            row = require_status(line)
        result["terminal"] = require_status(line, terminal=True)
        terminal_line = line
        print(line, flush=True)
        for first in range(0, CAPACITY, BLOCK):
            result["triples"].extend(decode_block(uart.raw_query(f"ADC 3PH READ {first}"), first))
        result["crc32"] = verify_capture(terminal_line, result["triples"])
        result["all"] = analyze(result["triples"])
        with prefix.with_suffix(".csv").open("w", encoding="utf-8-sig", newline="") as file:
            writer = csv.writer(file)
            writer.writerow(("index", "nominal_trigger_time_us_not_measured",
                             "PA0_ADC1_U_raw", "PA1_ADC2_V_raw", "PC3_ADC1_W_raw_sequential"))
            writer.writerows((i, i * 50, *triple) for i, triple in enumerate(result["triples"]))
        result["csv"] = str(prefix.with_suffix(".csv"))
        result["after_status"] = require_status(uart.raw_query("ADC 3PH STATUS"), terminal=True)
        if result["after_status"]["CRC"] != result["crc32"]:
            raise RuntimeError("Capture changed during export")
        result["after_zero"] = require_service(uart.query("ZERO STATUS"))
        result["after_fw"] = require_confirmed(uart.query("FW STATUS"), slot)
        if result["after_fw"]["GEN"] != generation:
            raise RuntimeError("Metadata changed during acquisition")
        result["after_hardware"] = hardware()
        result["capture_pass"] = True
        print("THREE-PHASE RAW CAPTURE PASS: 4096 triples, full CRC; no zero/motor qualification", flush=True)
        print(json.dumps(result["all"], ensure_ascii=False), flush=True)
    except BaseException as error:
        result["failure"] = str(error)
        raise
    finally:
        result["sample_commands"] = uart.sample_commands if uart else 0
        result["uart"] = uart.lines if uart else []
        if port is not None:
            port.close()
        prefix.with_suffix(".json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print("Evidence: " + str(prefix.with_suffix(".json")), flush=True)


if __name__ == "__main__":
    main()
