"""Independently compare locked ADC1/2 UART samples to raw RAM; no halt/reset/write."""
import adc_pa1_only_readback as readback
from adc12_only_acceptance import OUTPUT, PINNED, pinned_image
from adc12_only_report import require_status, verify_capture


def main():
    readback.main(output_dir=OUTPUT, image_hashes=PINNED, image_provider=pinned_image,
                  expected_slot="A", capture_mask=3, status_checker=require_status,
                  capture_verifier=verify_capture, pass_label="ADC12 SWD READBACK",
                  pass_description="4096 U/V pairs + unsampled W padding match")


if __name__ == "__main__": main()
