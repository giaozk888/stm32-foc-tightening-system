"""Actual C reference admission policy; host mocks only, no board IO."""
from pathlib import Path
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]
GCC = r"D:\Qt\Tools\mingw1310_64\bin\gcc.exe"
FLAGS = ["ZERO_RETEST_BOOT", "ADC_DMA_RAW_DIAGNOSTIC", "ADC_DMA_THREE_PHASE_DIAGNOSTIC",
         "ADC_DMA_PARALLEL_DIAGNOSTIC", "ADC_DMA_PARALLEL_LONG_SAMPLE",
         "ADC_DMA_ADC12_ONLY_DIAGNOSTIC", "ADC_DMA_REFERENCE_INPUT_DIAGNOSTIC"]


class ReferenceOwnerTests(unittest.TestCase):
    def test_actual_owner_rejects_wrong_supply_and_never_publishes_zero(self):
        directory = ROOT / "tests/zero_adc_owner_build"
        directory.mkdir(exist_ok=True)
        target = directory / "reference.exe"
        subprocess.run([GCC, "-std=c11", "-O2", "-Wall", "-Wextra", "-Werror",
                        "-pedantic", "-UNDEBUG", *["-D" + flag for flag in FLAGS],
                        str(ROOT / "tests/adc_reference_owner_host.c"),
                        str(ROOT / "firmware_common/foc_current_zero.c"), "-o", str(target)], check=True)
        for scenario in range(100, 144):
            with self.subTest(scenario=scenario):
                subprocess.run([str(target), str(scenario)], check=True, capture_output=True, text=True)

    def test_incomplete_compile_profile_is_rejected(self):
        for missing in FLAGS[:-1]:
            args = [GCC, "-std=c11", "-fsyntax-only", *["-D" + flag for flag in FLAGS if flag != missing],
                    str(ROOT / "tests/adc_reference_owner_host.c")]
            process = subprocess.run(args, capture_output=True, text=True)
            self.assertNotEqual(process.returncode, 0)
            self.assertIn("Reference input capture requires", process.stderr)

    def test_cmake_default_off_and_strict_dependencies_in_both_apps(self):
        for app in ("foc2_app_a", "foc2_app_b"):
            source = (ROOT / app / "CMakeLists.txt").read_text(encoding="utf-8")
            self.assertIn('option(ADC_DMA_REFERENCE_INPUT_DIAGNOSTIC "Hard-off known-input raw capture with explicit drive-supply OFF/ON" OFF)', source)
            self.assertIn("Reference input contrast requires the standalone locked ADC1/2 long-sampling profile", source)
            self.assertIn("ADC_DMA_REFERENCE_INPUT_DIAGNOSTIC=1", source)


if __name__ == "__main__":
    unittest.main()
