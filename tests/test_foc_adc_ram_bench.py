"""Host result-decoder and safety contracts; no connection to hardware."""
import importlib.util
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
spec = importlib.util.spec_from_file_location("bench", ROOT / "tools/foc_adc_ram_test.py")
bench = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bench)

class BenchTests(unittest.TestCase):
    def test_async_clock_rejects_wrong_modes_divisors_dual_or_source(self):
        for presc in range(16):
            for mode in range(4):
                ccr = presc << 18 | mode << 16
                if presc == 2 and mode == 0:
                    bench.require_async_adc_clock(ccr, 0x20000000)
                else:
                    with self.subTest(presc=presc, mode=mode), self.assertRaises(RuntimeError):
                        bench.require_async_adc_clock(ccr, 0x20000000)
        bench.require_async_adc_clock(0x00480000, 0x20000000 | 0x12345)
        for dual in range(1, 32):
            with self.subTest(dual=dual), self.assertRaises(RuntimeError):
                bench.require_async_adc_clock(0x00080000 | dual, 0x20000000)
        for source in (0, 0x10000000, 0x30000000):
            with self.subTest(source=source), self.assertRaises(RuntimeError):
                bench.require_async_adc_clock(0x00080000, source)

    def fixture(self):
        values = dict.fromkeys(bench.FIELDS, 0)
        values.update(elapsed_us=1000000, pairs=20005, irq_entries=20005,
                      raw_count=256, sum_u=256, sum_v=512, ss_u=256, ss_v=1024)
        return [values[k] for k in bench.FIELDS]

    def test_valid(self):
        case = bench.decode_case(self.fixture())
        self.assertTrue(case["digital_pass"])
        self.assertEqual(case["raw_std_u"], 0)

    def test_missing_pair_and_zero_run_rejected(self):
        for field in ("pair_misses", "deadline_misses", "plan_failures"):
            data = self.fixture(); data[bench.FIELDS.index(field)] = 1
            self.assertFalse(bench.decode_case(data)["digital_pass"])
        self.assertFalse(bench.decode_case([0] * 32)["digital_pass"])

    def test_mixed_block_not_stable_comparison(self):
        data = self.fixture(); data[bench.FIELDS.index("mixed_block")] = 1
        self.assertFalse(bench.decode_case(data)["raw_block_valid_for_stable_comparison"])

    def test_impossible_raw_statistics(self):
        data = self.fixture(); data[bench.FIELDS.index("ss_u")] = 0
        with self.assertRaises(ValueError): bench.decode_case(data)

    def test_source_safety_contracts(self):
        source = (ROOT / "tests/foc_adc_ram_bench.c").read_text(encoding="utf-8")
        self.assertNotIn("HAL_GPIO_WritePin", source)
        self.assertNotIn("GPIOC->BSRR = GPIO_PIN_6;", source)
        self.assertIn("GPIOC->BSRR = GPIO_PIN_6 << 16", source)
        self.assertIn("ADC1->IER = ADC_IER_JEOSIE", source)
        self.assertIn("ADC_ISR_OVR | ADC_ISR_JQOVF", source)
        self.assertIn("foc_bench_report.fault == 0", source)
        self.assertIn("__BKPT(0)", source)
        self.assertIn("FocAdcTiming_Commit", source)
        self.assertIn("duration > 10000000", source)

if __name__ == "__main__": unittest.main()
