"""Read-only full pinned B code and both actual raw arrays; W is padding."""
import adc_pa1_only_readback as shared
from adc_reference_double_acceptance import OUTPUT, PINNED, pinned_image
from adc_reference_double_report import require_status, verify_capture


def main():
    shared.main(output_dir=OUTPUT, image_hashes=PINNED, image_provider=pinned_image,
                expected_slot="B", capture_mask=3, status_checker=require_status,
                capture_verifier=verify_capture, capacity=8192, stored_channels=2,
                pass_label="DOUBLE GPIO LOW SWD READBACK",
                pass_description="8192 actual U/V ADC pairs match; input wiring is recorded in capture; W padding explicitly synthesized")


if __name__ == "__main__": main()
