"""One IU/IV raw observation with hard-off outputs; no zero publication.

Uses the exact existing B ADC12/8192 diagnostic without changing firmware,
protection thresholds or supply admission. These inputs are not grounded.
"""
import argparse
from functools import partial
import sys
import adc_parallel_sample as parallel
from adc_reference_double_sample import deployment_identity
from adc_reference_double_acceptance import PINNED, OUTPUT, require_fresh_double
from adc_reference_double_report import CAPACITY, require_status, verify_capture, decode_block, analyze
from adc_reference_sample import ReferenceUart
from adc_reference_report import require_supply
from adc_owner_acceptance import require_owner_service


def main():
    parser = argparse.ArgumentParser(add_help=False)
    for name in ("iu-iv-connected", "all-six-connected", "common-ground-replaced",
                 "diagnostic-ground-resistors-removed"):
        parser.add_argument("--" + name, action="store_true")
    args, rest = parser.parse_known_args()
    if not all(vars(args).values()):
        parser.error("IU/IV sensor wiring, removed diagnostic shunts, six controls and replacement ground required")
    sys.argv = [sys.argv[0], *rest]
    parallel.main(deployment_checker=deployment_identity, fresh_checker=require_fresh_double,
        service_checker=require_owner_service, image_hashes=PINNED, output_dir=OUTPUT,
        status_checker=partial(require_status, power="ON"), capture_verifier=partial(verify_capture, power="ON"),
        capture_analyzer=analyze, quiet_acquisition=True, quiet_wait_seconds=1.,
        capacity=CAPACITY, block_decoder=decode_block, uart_factory=ReferenceUart,
        supply_checker=partial(require_supply, power="ON"), sample_command="ADC PAR SAMPLE ON", supply_state="ON",
        capture_label="ADC12 GPIO_LOW DOUBLE IU_IV_SENSOR",
        raw_mapping={"U": "driver IU->PA0/ADC1; not grounded; diagnostic ground resistor removed per instruction",
                     "V": "driver IV->PA1/ADC2; not grounded; diagnostic ground resistor removed per instruction",
                     "W": "UNSAMPLED export zero padding; no W DMA storage",
                     "INPUT_WIRING_BASIS": "In-context user wiring completion; not independently measured",
                     "CONTROL_WIRING_USER_CONFIRMED": "All six connected; replacement inter-board common ground retained; motor power leads disconnected"},
        csv_headers=("index", "nominal_trigger_time_us_not_measured", "PA0_IU_SENSOR_RAW", "PA1_IV_SENSOR_RAW", "W_UNSAMPLED_PADDING"))


if __name__ == "__main__": main()
