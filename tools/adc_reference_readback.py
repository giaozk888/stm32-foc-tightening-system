"""Independent code and full raw-RAM integrity check; never reset/halt/write."""
import adc_pa1_only_readback as readback
from adc_reference_acceptance import OUTPUT, PINNED, pinned_image
from adc_reference_report import require_status, verify_capture


def main():
    readback.main(output_dir=OUTPUT, image_hashes=PINNED, image_provider=pinned_image,
                  expected_slot="B", capture_mask=3, status_checker=require_status,
                  capture_verifier=verify_capture, pass_label="REFERENCE SWD READBACK",
                  pass_description="4096 U/V pairs + unsampled W padding match")


if __name__ == "__main__": main()
