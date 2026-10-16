"""One extended grounded-input capture; explicit control wiring; no reset."""
import argparse
from functools import partial
import sys
import adc_parallel_sample as parallel
from adc_reference_double_acceptance import PINNED, OUTPUT, PROFILE, require_fresh_double
from adc_reference_double_report import CAPACITY, require_status, verify_capture, decode_block, analyze
from adc_reference_sample import ReferenceUart
from adc_reference_report import require_supply
from adc_owner_sample import deployment_identity as owner_identity
from adc_owner_acceptance import require_owner_service


def deployment_identity(evidence):
    slot, gen = owner_identity(evidence, image_hashes=PINNED, profile=PROFILE)
    if slot != "B": raise RuntimeError("Extended confirmed B required")
    raw = evidence.get("three_phase_service", {}).get("raw", {})
    require_status("1 OK ADC3PAR " + " ".join(f"{k}={v}" for k, v in raw.items()), power="NONE")
    for k, v in (("STATE", "0"), ("NU", "0"), ("NV", "0"), ("NW", "0"),
                 ("IRQ", "0,0,0"), ("ERR", "0,0,0"), ("SMP_CHECK", "0")):
        if raw.get(k) != v: raise RuntimeError("Fresh extended deployment proof required")
    return slot, gen


def main():
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--both-ground-confirmed", action="store_true")
    wiring = parser.add_mutually_exclusive_group(required=True)
    wiring.add_argument("--all-six-connected", action="store_true")
    wiring.add_argument("--only-disconnected-control", choices=("WL",))
    parser.add_argument("--common-ground-replaced", action="store_true")
    args, rest = parser.parse_known_args()
    if not args.both_ground_confirmed:
        parser.error("Unchanged both-ground inputs required")
    if args.common_ground_replaced and not args.all_six_connected:
        parser.error("Ground-line replacement contrast requires all six controls connected")
    description = ("ONLY WL disconnected; UH,VH,WH,UL,VL connected; common ground unchanged; "
                   "in-context unplug statement interpreted as WL, not electrically measured"
                   if args.only_disconnected_control else
                   "WL reconnected/replacement wire; all six connected; common ground unchanged")
    if args.common_ground_replaced:
        description = ("All six controls connected; only existing inter-board signal GND replaced by a "
                       "shorter direct wire; completed per user reply, not independently measured; "
                       "PA0/PA1 ground resistors and other wiring inherited unchanged")
    sys.argv = [sys.argv[0], *rest]
    parallel.main(deployment_checker=deployment_identity, fresh_checker=require_fresh_double,
        service_checker=require_owner_service, image_hashes=PINNED, output_dir=OUTPUT,
        status_checker=partial(require_status, power="ON"), capture_verifier=partial(verify_capture, power="ON"),
        capture_analyzer=analyze, quiet_acquisition=True, quiet_wait_seconds=1.,
        capacity=CAPACITY, block_decoder=decode_block, uart_factory=ReferenceUart,
        supply_checker=partial(require_supply, power="ON"), sample_command="ADC PAR SAMPLE ON", supply_state="ON",
        capture_label="ADC12 GPIO_LOW DOUBLE " + ("ALL_CONNECTED_GROUND_REPLACED" if args.common_ground_replaced else "ONLY_WL_DISCONNECTED" if args.only_disconnected_control else "ALL_CONNECTED"),
        raw_mapping={"U": "PA0 via about 1 kohm to MCU GND; IU/IV disconnected; inherited unchanged ground wiring",
                     "V": "PA1 via about 1 kohm to MCU GND; IU/IV disconnected; inherited unchanged ground wiring",
                     "W": "UNSAMPLED export zero padding; no W DMA storage",
                     "CONTROL_WIRING_USER_CONFIRMED": description},
        csv_headers=("index", "nominal_trigger_time_us_not_measured", "PA0_GROUNDED_RAW", "PA1_GROUNDED_RAW", "W_UNSAMPLED_PADDING"))


if __name__ == "__main__": main()
