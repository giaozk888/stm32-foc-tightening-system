"""Pure deployment pinning, export validation, and one-shot host checks."""
import hashlib
from pathlib import Path
import struct
import sys
import unittest
import zlib

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import adc_dma_raw_acceptance as deployment
import adc_dma_raw_sample as sample


class ToolsTests(unittest.TestCase):
    def test_exact_pinned_slot_images(self):
        for slot in "AB":
            path, image = deployment.pinned_image(slot)
            self.assertEqual(deployment.deploy.image_info(image)[0], slot)
            self.assertEqual(hashlib.sha256(image).hexdigest(), deployment.PINNED[slot])
            self.assertTrue(path.is_file())

    def test_status_rejects_partial_dma_errors_unlocked_outputs(self):
        good = "1 OK ADC_DMA LOCK=1 SD=0 MOE=0 CCER=0 CEN=0 FOC=0 STATE=4 REASON=0 " + \
               "NU=4096 NV=4096 IRQ=1,1 ERR=0,0 RESTORE=1 CRC=12345678 CAP=4096"
        sample.require_status(good, terminal=True)
        for old, new in (("LOCK=1", "LOCK=0"), ("SD=0", "SD=1"), ("MOE=0", "MOE=1"),
                         ("CEN=0", "CEN=1"), ("STATE=4", "STATE=5"), ("NU=4096", "NU=4095"),
                         ("NV=4096", "NV=0"), ("IRQ=1,1", "IRQ=1,0"), ("ERR=0,0", "ERR=0,2"),
                         ("RESTORE=1", "RESTORE=0")):
            with self.assertRaises(RuntimeError):
                sample.require_status(good.replace(old, new), terminal=True)

    def test_index_length_and_sample_width_checked(self):
        line = "1 OK ADC_DMA_DATA I=0 N=16 UV=" + "06160616" * 16
        self.assertEqual(sample.decode_block(line, 0), [(1558, 1558)] * 16)
        for bad in (line.replace("I=0", "I=16"), line.replace("N=16", "N=15"),
                    line[:-1], line.replace("06160616", "FFFF0616", 1)):
            with self.assertRaises(RuntimeError):
                sample.decode_block(bad, 0)
        pairs = sample.decode_block(line, 0)
        self.assertEqual(len(b"".join(struct.pack("<HH", *p) for p in pairs)), 64)

    def test_summary_retains_spikes_and_distinguishes_trim(self):
        pairs = [(1558, 1558)] * 4096
        pairs[1] = (0, 4095)
        pairs[1000] = (1257, 1412)
        report = sample.analyze(pairs, 1558)
        self.assertEqual(report["U"]["outside_indices"], [1, 1000])
        self.assertEqual(report["V"]["outside_indices"], [1, 1000])
        self.assertEqual(report["both_outside_nominal_100"], 2)
        self.assertEqual(report["U"]["min"], 0)
        trimmed = sample.analyze(pairs, 1558, 64)
        self.assertEqual(trimmed["count"], 4032)
        self.assertEqual(trimmed["U"]["outside_indices"], [1000])
        self.assertEqual(pairs[1], (0, 4095))

    def test_one_shot_never_resends_when_ack_missing(self):
        class Port:
            def __init__(self): self.writes = []
            def write(self, data): self.writes.append(data)
        port = Port()
        uart = sample.RawUart(port)
        with self.assertRaises(TimeoutError): uart.raw_query("ADC DMA SAMPLE", timeout=0)
        with self.assertRaises(RuntimeError): uart.raw_query("ADC DMA SAMPLE", timeout=0)
        self.assertEqual(uart.sample_commands, 1)
        self.assertEqual(len(port.writes), 1)

    def test_host_contains_no_reset_unlock_clear_or_motion_commands(self):
        source = Path(sample.__file__).read_text(encoding="utf-8")
        for bad in ('"FW END"', '"FW CONFIRM"', '"START"', '"CLEAR"', '"-rst"', '"ZERO SAMPLE"'):
            self.assertNotIn(bad, source)
        self.assertIn("require_registers", source)
        self.assertIn("require_async_registers", source)
        self.assertIn('supply["VDDA_BOOT_MV"]', source)


if __name__ == "__main__":
    unittest.main()
