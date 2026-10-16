"""One finite parallel three-ADC raw capture with outputs locked; never drive a motor.

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

from adc_parallel_acceptance import (
    OUTPUT, PINNED, ParallelUart, require_fresh_parallel,
    CLI, SN, ADDRESSES, CLOCK_ADDRESSES, require_registers, require_async_registers,
)
from adc_parallel_report import CAPACITY, BLOCK, require_status, decode_block, verify_capture, analyze
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
        raise RuntimeError("Successful exact parallel three-ADC locked deployment required")
    fw = evidence.get("final_fw", {})
    if (fw.get("CURRENT") != slot or fw.get("CONFIRMED") != slot or
            fw.get("PENDING") != "-" or fw.get("ATTEMPTS") != "0" or fw.get("ACTIVE") != "0" or
            not str(fw.get("GEN", "")).isdigit()):
        raise RuntimeError("Deployment confirmation/generation missing")
    return slot, fw["GEN"]


def await_terminal(uart, line, status_checker, *, quiet_acquisition=False, quiet_wait_seconds=.5):
    """No SAMPLE resend. Quiet contrast skips host polling, not all MCU traffic."""
    row = status_checker(line)
    if row.get("STATE") in ("4", "5"):
        return line
    if quiet_acquisition:
        # The pinned acquisition is 205 ms with a bounded firmware timeout.
        # Keep the host silent after the SAMPLE ACK; one final query only.
        time.sleep(quiet_wait_seconds)
        line = uart.raw_query("ADC PAR STATUS", timeout=.5)
        if status_checker(line).get("STATE") not in ("4", "5"):
            raise RuntimeError("Quiet capture not terminal; no polling/retry/reset")
        return line
    deadline = time.monotonic() + 3
    while row.get("STATE") not in ("4", "5"):
        if time.monotonic() >= deadline:
            raise TimeoutError("Acquisition deadline exceeded; no repeat/reset")
        time.sleep(.05)
        line = uart.raw_query("ADC PAR STATUS", timeout=.5)
        row = status_checker(line)
    return line


def main(*, deployment_checker=deployment_identity, fresh_checker=require_fresh_parallel,
         service_checker=require_service, image_hashes=PINNED, output_dir=OUTPUT,
         status_checker=require_status, capture_verifier=verify_capture, capture_analyzer=analyze,
         raw_mapping=None, csv_headers=None, capture_label="PARALLEL", quiet_acquisition=False,
         uart_factory=ParallelUart, supply_checker=require_supply,
         sample_command="ADC PAR SAMPLE", supply_state="ON", capacity=CAPACITY,
         block_decoder=decode_block, quiet_wait_seconds=.5):
    if capacity not in (4096, 8192) or not .5 <= quiet_wait_seconds <= 2:
        raise ValueError("Only bounded offline-validated capture sizes/waits admitted")
    if supply_state not in ("ON", "OFF"):
        raise ValueError("Explicit ON/OFF supply state required")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--deployment-evidence", type=Path, required=True)
    parser.add_argument("--inspect", action="store_true")
    parser.add_argument("--allow-sample", action="store_true")
    parser.add_argument("--motor-leads-disconnected", action="store_true")
    parser.add_argument("--supply-12v-0p5a-no-alarm", action="store_true")
    parser.add_argument("--drive-12v-off", action="store_true")
    args = parser.parse_args()
    if args.inspect == args.allow_sample:
        parser.error("Select read-only inspection OR one explicitly authorized sample")
    physical_supply = (args.drive_12v_off and not args.supply_12v_0p5a_no_alarm) if supply_state == "OFF" else (
        args.supply_12v_0p5a_no_alarm and not args.drive_12v_off)
    if args.allow_sample and not (args.motor_leads_disconnected and physical_supply):
        parser.error("Current physical conditions required before sampling")
    evidence = json.loads(args.deployment_evidence.read_text(encoding="utf-8"))
    slot, generation = deployment_checker(evidence)
    output_dir.mkdir(parents=True, exist_ok=True)
    prefix = output_dir / f"capture-{time.time_ns()}"
    result = {"capture_pass": False, "inspection_pass": False, "inspect_only": args.inspect,
              "zero_qualified": False, "motor_qualified": False, "signal_quality_qualified": False,
              "flash_write": False, "reset": False, "motion_commands": False,
              "thresholds_changed": False, "triples": [], "steps": [],
              "host_quiet_after_sample_ack": bool(quiet_acquisition),
              "host_quiet_wait_seconds": quiet_wait_seconds if quiet_acquisition else 0,
              "all_mcu_communication_suppressed": False,
              "deployment_evidence": str(args.deployment_evidence), "sha256": image_hashes[slot],
              "motor_leads_disconnected_user_confirmed": args.motor_leads_disconnected,
              "supply_12v_0p5a_no_alarm_user_confirmed": args.supply_12v_0p5a_no_alarm,
              "drive_12v_off_user_confirmed": args.drive_12v_off,
              "requested_supply_state": supply_state,
              "raw_mapping": raw_mapping or {"U": "AMP_IU/PA0/ADC1_IN1", "V": "AMP_IV/PA1/ADC2_IN2",
                              "W": "AMP_IW/PA8/ADC5_IN1 common event"}}
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
        uart = uart_factory(port)
        result["before_fw"] = require_confirmed(uart.query("FW STATUS", 3), slot)
        if result["before_fw"]["GEN"] != generation:
            raise RuntimeError("Metadata generation changed after deployment")
        result["before_service"] = fresh_checker(uart)
        if args.inspect:
            result["inspection_pass"] = True
            print(capture_label + " READ-ONLY PASS: fresh locked diagnostic; no sample", flush=True)
            return
        result["supply_estimate"] = supply_checker(uart.query("ANALOG VOLT"))
        line = uart.raw_query(sample_command)
        line = await_terminal(uart, line, status_checker, quiet_acquisition=quiet_acquisition,
                              quiet_wait_seconds=quiet_wait_seconds)
        result["terminal"] = status_checker(line, terminal=True)
        terminal_line = line
        print(line, flush=True)
        for first in range(0, capacity, BLOCK):
            result["triples"].extend(block_decoder(uart.raw_query(f"ADC PAR READ {first}"), first))
        result["crc32"] = capture_verifier(terminal_line, result["triples"])
        result["all"] = capture_analyzer(result["triples"])
        with prefix.with_suffix(".csv").open("w", encoding="utf-8-sig", newline="") as file:
            writer = csv.writer(file)
            writer.writerow(csv_headers or ("index", "nominal_trigger_time_us_not_measured",
                             "PA0_ADC1_U_raw", "PA1_ADC2_V_raw", "PA8_ADC5_W_raw"))
            writer.writerows((i, i * 50, *triple) for i, triple in enumerate(result["triples"]))
        result["csv"] = str(prefix.with_suffix(".csv"))
        result["after_status"] = status_checker(uart.raw_query("ADC PAR STATUS"), terminal=True)
        if result["after_status"]["CRC"] != result["crc32"]:
            raise RuntimeError("Capture changed during export")
        result["after_zero"] = service_checker(uart.query("ZERO STATUS"))
        result["after_fw"] = require_confirmed(uart.query("FW STATUS"), slot)
        if result["after_fw"]["GEN"] != generation:
            raise RuntimeError("Metadata changed during acquisition")
        result["after_hardware"] = hardware()
        result["capture_pass"] = True
        print(capture_label + " RAW CAPTURE PASS: full CRC; no zero/motor qualification", flush=True)
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
