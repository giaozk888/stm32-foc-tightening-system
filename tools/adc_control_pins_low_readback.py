"""Full exact A image and all raw samples read-only; no reset/halt/write."""
import adc_pa1_only_readback as readback
from adc_control_pins_low_acceptance import OUTPUT, PINNED, pinned_image, require_status, verify_capture

def main():
    readback.main(output_dir=OUTPUT, image_hashes=PINNED, image_provider=pinned_image,
                  expected_slot="A", capture_mask=3, status_checker=require_status,
                  capture_verifier=verify_capture, pass_label="GPIO LOW SWD READBACK",
                  pass_description="4096 dual-ground U/V pairs + unsampled W padding match")

if __name__ == "__main__": main()
