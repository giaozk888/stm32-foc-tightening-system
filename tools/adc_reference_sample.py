"""One raw ADC1/2 known-input capture with explicit actual drive-power state."""
import argparse
import math
import re
import sys
import time
from functools import partial
import adc_parallel_sample as parallel
from adc_parallel_acceptance import ParallelUart
from adc_owner_acceptance import require_owner_service
from adc_owner_sample import deployment_identity as owner_identity
from adc_reference_acceptance import OUTPUT, PINNED, PROFILE, require_fresh_reference
from adc_reference_report import require_status, verify_capture, require_supply, analyze


class ReferenceUart(ParallelUart):
    def raw_query(self, command, timeout=2):
        if command in ("ADC PAR SAMPLE OFF", "ADC PAR SAMPLE ON"):
            if self.sample_commands:
                raise RuntimeError("No repeated/automatic reference sample allowed")
            self.sample_commands += 1
        elif command != "ADC PAR STATUS" and not re.fullmatch(r"ADC PAR READ \d+", command):
            raise ValueError("Only explicit reference OFF/ON sample or raw read admitted")
        self.request += 1
        request = self.request
        self.port.write(f"{request} {command}\r\n".encode("ascii"))
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            line = self.read_line(.05)
            if line is not None:
                self.dispatch(line)
                if line.startswith(f"{request} "):
                    if not line.startswith(f"{request} OK "):
                        raise RuntimeError(line)
                    return line
        raise TimeoutError("No ACK; do not resend reference capture: " + command)


def deployment_identity(evidence):
    slot, generation = owner_identity(evidence, image_hashes=PINNED, profile=PROFILE)
    raw = evidence.get("three_phase_service", {}).get("raw", {})
    if slot != "B" or any(raw.get(key) != value for key, value in (
            ("MODE", "ADC12_REFERENCE"), ("CAPTURE_MASK", "3"), ("CH", "2"),
            ("REAL_W", "0"), ("PAD_W", "ZERO_UNSAMPLED"), ("SMP_CYCLES", "247.5"),
            ("SMP_CHECK", "0"), ("SUPPLY_POLICY", "EXPLICIT_OFF_ON"), ("POWER", "NONE"),
            ("ADMIT_MV", "0"))):
        raise RuntimeError("Only normally deployed fresh reference-input B admitted")
    return slot, generation


def main():
    parser = argparse.ArgumentParser(add_help=False)
    choice = parser.add_mutually_exclusive_group(required=True)
    choice.add_argument("--power-off", action="store_true")
    choice.add_argument("--power-on", action="store_true")
    parser.add_argument("--same-divider-confirmed", action="store_true")
    parser.add_argument("--pa0-measured-volts", type=float, required=True)
    parser.add_argument("--pa1-measured-volts", type=float, required=True)
    args, remaining = parser.parse_known_args()
    if not args.same_divider_confirmed or not all(math.isfinite(v) and 1.4 <= v <= 1.9 for v in (
            args.pa0_measured_volts, args.pa1_measured_volts)):
        parser.error("Known same-divider inputs, IU/IV disconnected, both measured 1.4..1.9 V required")
    power = "OFF" if args.power_off else "ON"
    sys.argv = [sys.argv[0], *remaining]
    parallel.main(deployment_checker=deployment_identity, fresh_checker=require_fresh_reference,
                  service_checker=require_owner_service, image_hashes=PINNED, output_dir=OUTPUT,
                  status_checker=partial(require_status, power=power),
                  capture_verifier=partial(verify_capture, power=power), capture_analyzer=analyze,
                  capture_label="ADC12 REFERENCE " + power, quiet_acquisition=True,
                  uart_factory=ReferenceUart, supply_checker=partial(require_supply, power=power),
                  sample_command="ADC PAR SAMPLE " + power, supply_state=power,
                  raw_mapping={"U": f"PA0/ADC1 same divider via approximately 1k ohm; IU/IV disconnected; user measured {args.pa0_measured_volts:g} V to MCU GND",
                               "V": f"PA1/ADC2 same known divider; user measured {args.pa1_measured_volts:g} V to MCU GND",
                               "W": "UNSAMPLED zero padding; IU/IV disconnected"},
                  csv_headers=("index", "nominal_trigger_time_us_not_measured", "PA0_REFERENCE_RAW",
                               "PA1_REFERENCE_RAW", "W_UNSAMPLED_PADDING"))


if __name__ == "__main__": main()
