"""Offline source/predicate contracts, not powered current-protection validation."""
from pathlib import Path
import re
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]


class PhaseCurrentTripTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sources = [
            (ROOT / f"foc2_app_{slot}/Core/Src/main.c").read_text(encoding="utf-8")
            for slot in "ab"
        ]

    def test_both_slots_use_requested_four_amp_threshold(self):
        for source in self.sources:
            self.assertRegex(source, r"#define\s+FOC_CURRENT_TRIP_A\s+4\.0f\b")
            self.assertIn("Phase trip      : 4.0A; powered validation pending", source)
            self.assertNotIn("Phase trip      : 2.0A unchanged", source)

    def test_predicate_checks_absolute_value_of_all_three_phases(self):
        pattern = (r"if\s*\(\s*\(fabsf\(iu_A\) > FOC_CURRENT_TRIP_A\)\s*\|\|\s*"
                   r"\(fabsf\(iv_A\) > FOC_CURRENT_TRIP_A\)\s*\|\|\s*"
                   r"\(fabsf\(iw_A\) > FOC_CURRENT_TRIP_A\)\s*\)\s*\{")
        for source in self.sources:
            # Compile-preprocess the default predicate; no diagnostic option.
            start=source.index('    if (\n#if defined(FOC_CURRENT_TREND4)\n')
            filtered=source.index('        (fabsf(iu_A)',start)
            end=source.index('    {',filtered)+len('    {')
            gate=source[start:filtered]
            self.assertIn('#else\n        physical_trip ||\n#endif',gate)
            pp=subprocess.run([r'D:\Qt\Tools\mingw1310_64\bin\gcc.exe',
                '-E','-P','-x','c','-'],input=source[start:end],capture_output=True,
                text=True,check=True).stdout
            self.assertRegex(pp, pattern)
            self.assertIn("iw_A = -(iu_A + iv_A);", source)

    def test_trip_still_latches_fault_and_disables_bridge(self):
        for source in self.sources:
            start = source.index("    if (\n#if defined(FOC_CURRENT_TREND4)\n")
            gate = source[start:source.index("if (foc_current_trip_snapshot.valid", start)]
            for statement in ("foc_fault_reason = 1U;", "foc_fault = 1U;", "foc_enable = 0U;",
                              "HAL_GPIO_WritePin(DRIVER_SD_GPIO_Port,", "DRIVER_SD_Pin,",
                              "GPIO_PIN_RESET);", "PWM_SetDuty(0.5f, 0.5f, 0.5f);"):
                self.assertIn(statement, gate)

    def test_explicit_200ma_direct_limit_other_limits_unchanged(self):
        for source in self.sources:
            for name, value in (("MOTOR_SPEED_IQ_LIMIT_A", "0.40"),
                                ("SPEED_IQ_LIMIT_A", "0.40"),
                                ("MOTOR_DIRECT_IQ_LIMIT_A", "0.20"),
                                ("FOC_VOLTAGE_LIMIT_V", "0.80")):
                self.assertRegex(source, rf"#define\s+{name}\s+{re.escape(value)}f\b")

    def test_strict_threshold_boundary_and_reconstructed_w(self):
        # This is a source-bound predicate mirror, not an ADC or ISR emulator.
        thresholds = [float(re.search(r"#define\s+FOC_CURRENT_TRIP_A\s+([\d.]+)f", s)[1])
                      for s in self.sources]
        for threshold in thresholds:
            for phase in range(3):
                for sign in (-1, 1):
                    for magnitude, expected in ((3.99, False), (4.0, False), (4.01, True)):
                        currents = [0.0, 0.0, 0.0]
                        currents[phase] = sign * magnitude
                        with self.subTest(phase=phase, sign=sign, magnitude=magnitude):
                            self.assertEqual(any(abs(i) > threshold for i in currents), expected)
            iu, iv = 2.01, 2.01
            iw = -(iu + iv)
            self.assertLess(abs(iu), threshold)
            self.assertLess(abs(iv), threshold)
            self.assertGreater(abs(iw), threshold)


if __name__ == "__main__":
    unittest.main()
