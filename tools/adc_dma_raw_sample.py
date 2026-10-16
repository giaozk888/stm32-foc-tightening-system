"""One finite IU/IV raw DMA capture; read-only export after DMA stops.

Requires pinned successful deployment evidence, explicit disconnected motor
leads, 12 V/0.5 A/no-alarm confirmation. Never resets, flashes, retries a
sample, changes thresholds, enables PWM outputs, clears faults or publishes zero.
CSV index time is NOMINAL 20 kHz, not a measured per-sample timestamp.
"""
import argparse
import csv
import json
import re
import statistics
import struct
import subprocess
import time
import zlib
from pathlib import Path

from adc_dma_raw_acceptance import PINNED, ROOT, OUTPUT
from zero_async_clock_acceptance import CLI, SN, ADDRESSES, CLOCK_ADDRESSES, require_async_registers
from zero_span100_acceptance import require_registers, AcceptanceUart
from zero_retest_deploy import require_confirmed, require_service
from zero_retest_sample import fields, require_supply


def require_status(line, terminal=False):
    row = fields(line)
    for key, value in (("LOCK", "1"), ("SD", "0"), ("MOE", "0"), ("CCER", "0"), ("FOC", "0")):
        if row.get(key) != value:
            raise RuntimeError("ADC DMA output proof failed: " + line)
    if terminal and any(row.get(k) != v for k, v in
                        (("STATE", "4"), ("REASON", "0"), ("CEN", "0"), ("NU", "4096"),
                         ("NV", "4096"), ("IRQ", "1,1"), ("ERR", "0,0"), ("RESTORE", "1"))):
        raise RuntimeError("Incomplete/failed capture; raw buffer not accepted: " + line)
    return row


def decode_block(line, first):
    row = fields(line)
    if row.get("I") != str(first) or row.get("N") != "16" or not re.fullmatch(r"[0-9A-F]{128}", row.get("UV", "")):
        raise RuntimeError("Wrong index/size/hex in raw export")
    values = row["UV"]
    pairs = [(int(values[i:i + 4], 16), int(values[i + 4:i + 8], 16)) for i in range(0, 128, 8)]
    if any(a > 4095 or b > 4095 for a, b in pairs):
        raise RuntimeError("Raw export is not 12-bit ADC data")
    return pairs


def analyze(pairs, nominal, trim=0):
    report = {"count": len(pairs) - trim, "trim_first": trim,
              "trim_is_reporting_only_all_raw_samples_retained": True}
    for index, name in enumerate(("U", "V")):
        data = [p[index] for p in pairs[trim:]]
        deltas = [abs(b - a) for a, b in zip(data, data[1:])]
        report[name] = {"min": min(data), "max": max(data), "span": max(data) - min(data),
                        "mean": round(statistics.mean(data), 3),
                        "stddev_population": round(statistics.pstdev(data), 3),
                        "max_adjacent_step": max(deltas, default=0),
                        "steps_over_60": sum(d > 60 for d in deltas),
                        "outside_nominal_100": sum(abs(d - nominal) > 100 for d in data),
                        "outside_indices": [i + trim for i, d in enumerate(data) if abs(d - nominal) > 100],
                        "half_mean_drift": round(abs(statistics.mean(data[:len(data)//2]) -
                                                       statistics.mean(data[len(data)//2:])), 3)}
    report["both_outside_nominal_100"] = sum(abs(a - nominal) > 100 and abs(b - nominal) > 100
                                              for a, b in pairs[trim:])
    return report


class RawUart(AcceptanceUart):
    def __init__(self, port):
        super().__init__(port)
        self.sample_commands = 0

    def raw_query(self, command, timeout=2):
        if command == "ADC DMA SAMPLE":
            if self.sample_commands:
                raise RuntimeError("No repeated/automatic sample allowed")
            self.sample_commands += 1
        elif command != "ADC DMA STATUS" and not re.fullmatch(r"ADC DMA READ \d+", command):
            raise ValueError("Unsupported raw diagnostic command")
        self.request += 1
        self.port.write(f"{self.request} {command}\r\n".encode("ascii"))
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            line = self.read_line(.05)
            if line is None:
                continue
            self.dispatch(line)
            if line.startswith(f"{self.request} "):
                if not line.startswith(f"{self.request} OK "):
                    raise RuntimeError(line)
                return line
        raise TimeoutError("No ACK; never resend acquisition: " + command)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--deployment-evidence", type=Path, required=True)
    parser.add_argument("--allow-sample", action="store_true")
    parser.add_argument("--motor-leads-disconnected", action="store_true")
    parser.add_argument("--supply-12v-0p5a-no-alarm", action="store_true")
    parser.add_argument("--condition-label", default="")
    args = parser.parse_args()
    if not (args.allow_sample and args.motor_leads_disconnected and args.supply_12v_0p5a_no_alarm):
        parser.error("One-shot permission and current physical conditions required")
    evidence = json.loads(args.deployment_evidence.read_text(encoding="utf-8"))
    slot = evidence.get("target_slot")
    if (slot not in PINNED or evidence.get("pass") is not True or evidence.get("inspect_only") is not False or
            evidence.get("image_sha256") != PINNED[slot] or
            not evidence.get("final_flash", {}).get("all_protected_regions_unchanged")):
        raise RuntimeError("Successful pinned raw-diagnostic deployment required")
    generation = evidence["final_fw"]["GEN"]
    OUTPUT.mkdir(parents=True, exist_ok=True)
    prefix = OUTPUT / f"capture-{time.time_ns()}"
    result = {"capture_pass": False, "zero_qualified": False, "motor_qualified": False,
              "flash_write": False, "reset": False, "motion_commands": False,
              "thresholds_changed": False, "pairs": [], "steps": [],
              "deployment_evidence": str(args.deployment_evidence), "sha256": PINNED[slot],
              "physical_conditions_user_confirmed": "U/V/W disconnected, 12 V/0.5 A, no alarm",
              "raw_column_mapping": {"U": "PA0 / ADC1", "V": "PA1 / ADC2"},
              "driver_signal_mapping_is_in_condition_label": True,
              "condition_label": args.condition_label}
    port = uart = None

    def hardware():
        def read(addresses):
            command = []
            for address in addresses:
                command.extend(("-r32", hex(address), "4"))
            p = subprocess.run([CLI, "-c", "port=SWD", "mode=HOTPLUG", "freq=1000", "sn=" + SN,
                                *command], capture_output=True, text=True, errors="replace", timeout=30)
            output = p.stdout + p.stderr
            result["steps"].append({"args": command, "code": p.returncode, "output": output})
            if p.returncode or "Error:" in output:
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
        uart = RawUart(port)
        result["before_fw"] = require_confirmed(uart.query("FW STATUS", 3), slot)
        if result["before_fw"]["GEN"] != generation:
            raise RuntimeError("Generation changed after deployment")
        result["before_zero"] = require_service(uart.query("ZERO STATUS"))
        before = require_status(uart.raw_query("ADC DMA STATUS"))
        if before.get("STATE") != "0" or before.get("CEN") != "0":
            raise RuntimeError("Fresh unsampled raw diagnostic required; never reset automatically")
        supply = require_supply(uart.query("ANALOG VOLT"))
        result["supply_estimate"] = supply
        nominal = round(1250 * 4095 / int(supply["VDDA_BOOT_MV"]))
        result["nominal"] = nominal
        line = uart.raw_query("ADC DMA SAMPLE")
        require_status(line)
        deadline = time.monotonic() + 3
        while fields(line).get("STATE") not in ("4", "5"):
            if time.monotonic() >= deadline:
                raise TimeoutError("MCU-owned timeout exceeded; no reset/retry")
            time.sleep(.05)
            line = uart.raw_query("ADC DMA STATUS")
            require_status(line)
        print(line, flush=True)
        result["terminal"] = require_status(line, terminal=True)
        for first in range(0, 4096, 16):
            result["pairs"].extend(decode_block(uart.raw_query(f"ADC DMA READ {first}"), first))
        packed = b"".join(struct.pack("<HH", *pair) for pair in result["pairs"])
        crc = zlib.crc32(packed)
        if crc != int(result["terminal"]["CRC"], 16):
            raise RuntimeError("Whole-capture CRC mismatch")
        result["crc32"] = f"{crc:08X}"
        result["all"] = analyze(result["pairs"], nominal)
        result["trim64"] = analyze(result["pairs"], nominal, 64)
        with prefix.with_suffix(".csv").open("w", encoding="utf-8-sig", newline="") as file:
            writer = csv.writer(file)
            writer.writerow(("index", "nominal_time_us_not_measured", "PA0_ADC1_raw", "PA1_ADC2_raw"))
            writer.writerows((i, i * 50, *pair) for i, pair in enumerate(result["pairs"]))
        result["csv"] = str(prefix.with_suffix(".csv"))
        result["after_status"] = require_status(uart.raw_query("ADC DMA STATUS"), terminal=True)
        result["after_zero"] = require_service(uart.query("ZERO STATUS"))
        result["after_fw"] = require_confirmed(uart.query("FW STATUS"), slot)
        if result["after_fw"]["GEN"] != generation:
            raise RuntimeError("Metadata changed during raw acquisition")
        result["after_hardware"] = hardware()
        result["capture_pass"] = True
        print("RAW DMA CAPTURE PASS: 4096 pairs; CRC verified; no zero/motor qualification", flush=True)
        compact = {name: {key: value for key, value in result["all"][name].items()
                          if key != "outside_indices"} for name in ("U", "V")}
        print(json.dumps(compact, ensure_ascii=False), flush=True)
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
