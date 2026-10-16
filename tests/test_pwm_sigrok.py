"""Host regression using synthetic digital samples, never live hardware."""
import importlib.util
import io
import unittest
import zipfile
from pathlib import Path

spec = importlib.util.spec_from_file_location("pwm_analyze", Path(__file__).resolve().parents[1] / "tools" / "pwm_analyze_sigrok.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class PwmSamplesTest(unittest.TestCase):
    def wave(self):
        return (bytes([0]) * 12 + bytes([1]) * 1080 + bytes([0]) * 12 + bytes([2]) * 96) * 20

    def test_90_percent_and_deadtime(self):
        analyzer = module.Analyzer(24e6)
        analyzer.feed(self.wave())
        result = analyzer.result()
        self.assertEqual(result["channels"][0]["complete_cycles"], 19)
        self.assertEqual(result["channels"][0]["frequency_hz"], 20000)
        self.assertEqual(result["channels"][0]["duty_percent"], 90)
        self.assertEqual(result["channels"][1]["duty_percent"], 8)
        self.assertEqual(result["both_low_gap_ns"]["0_to_1"]["median"], 500)
        self.assertEqual(result["both_low_gap_ns"]["1_to_0"]["median"], 500)
        self.assertEqual(result["sampled_overlap_samples"], 0)

    def test_arbitrary_chunk_boundaries(self):
        single = module.Analyzer(24e6)
        single.feed(self.wave())
        chunks = module.Analyzer(24e6)
        data = self.wave()
        for position in range(0, len(data), 17):
            chunks.feed(data[position:position + 17])
        self.assertEqual(single.result(), chunks.result())

    def test_overlap_detected(self):
        data = bytearray(self.wave())
        data[100] = 3
        analyzer = module.Analyzer(24e6)
        analyzer.feed(data)
        self.assertEqual(analyzer.result()["sampled_overlap_samples"], 1)

    def test_terminal_overlap(self):
        analyzer = module.Analyzer(4e6)
        analyzer.feed(bytes([3]) * 7)
        self.assertEqual(analyzer.result()["sampled_overlap_samples"], 7)

    def test_static_has_no_cycles(self):
        analyzer = module.Analyzer(4e6)
        analyzer.feed(bytes([0]) * 1000)
        self.assertIsNone(analyzer.result()["channels"][0]["frequency_hz"])

    def test_file_samplerate_and_chunk_order(self):
        capture = io.BytesIO()
        metadata = "[device 1]\ncapturefile=logic-1\ntotal probes=8\nsamplerate=4 MHz\nunitsize=1\nprobe1=D0\nprobe2=D1\n"
        data = self.wave()
        with zipfile.ZipFile(capture, "w") as session:
            session.writestr("metadata", metadata)
            session.writestr("logic-1-2", data[123:])
            session.writestr("logic-1-1", data[:123])
        capture.seek(0)
        result = module.analyze_session(capture)
        self.assertEqual(result["samplerate_hz"], 4e6)
        self.assertEqual(result["channels"][0]["duty_percent"], 90)
        self.assertEqual(result["channels"][0]["channel"], "D0")
        self.assertFalse(result["digital_checks"]["deadtime_resolution_24mhz_or_better"])

    def test_invalid_samplerate(self):
        with self.assertRaises(ValueError):
            module.samplerate("unknown")

    def test_expected_physical_94_is_not_reference_95(self):
        capture = io.BytesIO()
        metadata = "[device 1]\ncapturefile=logic-1\ntotal probes=8\nsamplerate=24 MHz\nunitsize=1\n"
        data = (bytes([0]) * 12 + bytes([1]) * 1128 + bytes([0]) * 12 + bytes([2]) * 48) * 20
        with zipfile.ZipFile(capture, "w") as session:
            session.writestr("metadata", metadata)
            session.writestr("logic-1-1", data)
        capture.seek(0)
        result = module.analyze_session(capture, expected_main_duty=94)
        self.assertTrue(result["digital_checks"]["main_near_expected_percent"])
        self.assertFalse(result["digital_checks"]["main_near_90_percent"])
        self.assertEqual(result["expected_main_pin_duty_percent"], 94)

    def test_invalid_expected_duty(self):
        with self.assertRaises(ValueError):
            module.analyze_session(io.BytesIO(), expected_main_duty=101)


if __name__ == "__main__":
    unittest.main()
