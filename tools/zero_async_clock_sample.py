"""One zero acquisition after a verified async locked diagnostic deployment.

No flashing, reset, unlock, motion, fault clearing or automatic resampling.
The MCU owns the 5 s limit. Only its internal timer starts; PWM CCER/MOE/SD
must stay off. Physical 12 V / 0.5 A, no driver alarm and disconnected U/V/W
are user confirmations, not inferred from an ADC estimate or PROTECT field.
"""
import argparse
import json
import re
import subprocess
import time

from zero_async_clock_acceptance import (
    ROOT, OUTPUT, CLI, SN, PINNED, CLOCK_ADDRESSES, ADDRESSES,
    require_registers, require_async_registers,
)
from zero_retest_deploy import require_confirmed, require_service
from zero_retest_sample import (
    fields, require_supply, require_locked_sample, require_completed, OneShotUart,
)


def require_handover(record, *, image_hashes=PINNED):
    slot = record.get("target_slot")
    if (slot not in image_hashes or record.get("pass") is not True or
            record.get("inspect_only") is not False or
            record.get("image_sha256") != image_hashes[slot] or
            record.get("sampling_commands") is not False or
            record.get("motion_commands") is not False or
            not record.get("final_flash", {}).get("all_protected_regions_unchanged") or
            "async_clock_registers" not in record):
        raise RuntimeError("Successful pinned async deployment handover required")
    confirmed = record.get("final_fw", {})
    if any(confirmed.get(key) != value for key, value in
           (("CURRENT", slot), ("CONFIRMED", slot), ("PENDING", "-"),
            ("ATTEMPTS", "0"), ("ACTIVE", "0"))):
        raise RuntimeError("Deployment did not normally confirm its target")
    return slot, int(confirmed["GEN"])


def require_fresh_boot(line):
    require_service(line)
    row = require_locked_sample(line)  # Its parser retains digit-bearing U0/V0 keys.
    if any(row.get(key) != value for key, value in
           (("STATE", "0"), ("REASON", "0"), ("ADC", "0"),
            ("SET", "0"), ("N", "0"), ("U0", "0"), ("V0", "0"))):
        raise RuntimeError("Fresh unsampled diagnostic required; never reset automatically")
    return fields(line)


def main(*, handover_checker=require_handover, image_hashes=PINNED,
         output_dir=OUTPUT, clock_addresses=CLOCK_ADDRESSES,
         clock_checker=require_async_registers, fresh_checker=require_fresh_boot,
         sample_label="ASYNC ZERO", sample_guard=require_locked_sample,
         terminal_checker=require_completed, uart_factory=OneShotUart,
         filtered_diagnostic_only=False, extra_status_query=None,
         extra_status_checker=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--deployment-evidence", type=lambda x: ROOT / x, required=True)
    parser.add_argument("--allow-zero-sample", action="store_true")
    parser.add_argument("--motor-leads-disconnected", action="store_true")
    parser.add_argument("--supply-12v-0p5a-no-alarm", action="store_true")
    args = parser.parse_args()
    if not (args.allow_zero_sample and args.motor_leads_disconnected and
            args.supply_12v_0p5a_no_alarm):
        parser.error("One-shot permission and current physical test conditions required")
    handover = json.loads(args.deployment_evidence.read_text(encoding="utf-8"))
    slot, generation = handover_checker(handover)
    output_dir.mkdir(parents=True, exist_ok=True)
    target = output_dir / f"sample-{time.time_ns()}.json"
    result = {"acquisition_completed": False, "zero_qualified": False,
              "motor_qualified": False, "motion_commands": False,
              "reset": False, "flash_write": False, "thresholds_changed": False,
              "deployment_evidence": str(args.deployment_evidence),
              "image_sha256": image_hashes[slot], "expected_span_counts": 100,
              "physical_conditions": "User confirmed disconnected U/V/W, 12 V/0.5 A, no alarm",
              "protect_field_is_hardcoded_not_alarm_measurement": True, "steps": []}
    port = uart = None

    def read_hardware():
        def read(addresses):
            arguments = []
            for address in addresses:
                arguments.extend(("-r32", hex(address), "4"))
            process = subprocess.run(
                [CLI, "-c", "port=SWD", "mode=HOTPLUG", "freq=1000", "sn=" + SN,
                 *arguments], capture_output=True, text=True, errors="replace", timeout=30)
            out = process.stdout + process.stderr
            result["steps"].append({"args": arguments, "code": process.returncode, "output": out})
            if process.returncode or "Error:" in out:
                raise RuntimeError("Independent readback failed; no reset/retry")
            return out
        return {"outputs": require_registers(read(ADDRESSES), slot),
                "clock": clock_checker(read(clock_addresses))}

    try:
        result["before_hardware"] = read_hardware()
        import serial
        port = serial.Serial(port=None, baudrate=115200, timeout=.02, write_timeout=1)
        port.dtr = port.rts = False
        port.port = "COM5"
        port.open()
        uart = uart_factory(port)
        result["before_fw"] = require_confirmed(uart.query("FW STATUS", 3), slot)
        if int(result["before_fw"]["GEN"]) != generation:
            raise RuntimeError("Boot generation changed after deployment; no sample")
        result["before_zero"] = fresh_checker(uart.query("ZERO STATUS"))
        result["supply_estimate"] = require_supply(uart.query("ANALOG VOLT"))
        started = time.monotonic()
        line = uart.sample_once()
        sample_guard(line)
        print(line, flush=True)
        while fields(line).get("STATE") not in ("3", "4"):
            if time.monotonic() - started > 7:
                raise TimeoutError("No terminal evidence; do not repeat/reset/unlock")
            time.sleep(.15)
            line = uart.query("ZERO STATUS")
            sample_guard(line)
            print(line, flush=True)
        result["terminal_zero"] = terminal_checker(line)
        result["seconds"] = round(time.monotonic() - started, 3)
        result["acquisition_completed"] = True
        ready = fields(line)["STATE"] == "3"
        result["zero_qualified"] = ready and not filtered_diagnostic_only
        if filtered_diagnostic_only:
            result["filtered_zero_ready"] = ready
            result["filtered_diagnostic_only"] = True
        if extra_status_query:
            result["extra_status"] = extra_status_checker(uart.query(extra_status_query))
        result["after_zero"] = []
        for _ in range(10):
            time.sleep(.15)
            result["after_zero"].append(require_service(uart.query("ZERO STATUS")))
        result["after_fw"] = require_confirmed(uart.query("FW STATUS"), slot)
        if int(result["after_fw"]["GEN"]) != generation:
            raise RuntimeError("Unexpected metadata change during acquisition")
        result["after_hardware"] = read_hardware()
        result["outputs_stopped_after_sampling"] = True
        print(sample_label + " " + ("READY" if ready else "FAILED") +
              "; outputs off; motor/torque NOT qualified", flush=True)
    except BaseException as error:
        result["failure"] = str(error)
        raise
    finally:
        result["sample_commands"] = uart.sample_commands if uart else 0
        result["uart"] = uart.lines if uart else []
        if port is not None:
            port.close()
        target.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print("Evidence: " + str(target), flush=True)


if __name__ == "__main__":
    main()
