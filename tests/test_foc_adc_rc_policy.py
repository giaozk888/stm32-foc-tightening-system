"""Offline policy/compile gates; never opens a probe, serial port or device."""
import json
from pathlib import Path
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]
CC = Path(r"D:\Qt\Tools\mingw1310_64\bin\gcc.exe")


class RcSamplingPolicyTests(unittest.TestCase):
    def compile_header(self, defines):
        return subprocess.run(
            [str(CC), "-std=c11", "-Wall", "-Wextra", "-Werror", "-pedantic",
             "-fsyntax-only", "-x", "c", "-I", str(ROOT / "firmware_common"),
             *[f"-D{item}" for item in defines], "-"],
            input='#include "foc_adc_timing_stm32.h"\nint main(void) { return 0; }\n',
            text=True, capture_output=True, check=False)

    def test_direct_compile_requires_power_hard_off_and_valid_budget(self):
        base = ["FOC_ADC_RC_DIAGNOSTIC=1", "FOC_ADAPTIVE_FILTER_EXPERIMENT=1",
                "FOC_PROTECTED_CLOSED_LOOP=1"]
        for defines in ([], base, base + ["FOC_ADC_RC_MIN_LOW_ON_TICKS=3400"]):
            with self.subTest(allowed=defines):
                result = self.compile_header(defines)
                self.assertEqual(result.returncode, 0, result.stderr)
        rejected = [base[:1], base[:2], [base[0], base[2]],
                    base + ["FOC_LATEST_ORIGINAL_FSM=1"],
                    base + ["FOC_COMPACT_CLOSED_LOOP=1"],
                    base + ["FOC_ADC_RC_MIN_LOW_ON_TICKS=1699"],
                    base + ["FOC_ADC_RC_MIN_LOW_ON_TICKS=4250"]]
        for defines in rejected:
            with self.subTest(rejected=defines):
                result = self.compile_header(defines)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("RC", result.stderr)

    def test_ab_presets_are_separate_from_the_motor_candidate(self):
        for slot in "ab":
            app = ROOT / f"foc2_app_{slot}"
            data = json.loads((app / "CMakePresets.json").read_text(encoding="utf-8"))
            presets = {row["name"]: row for row in data["configurePresets"]}

            def resolve(name):
                row = presets[name]
                inherited = row.get("inherits")
                result = resolve(inherited) if inherited else {}
                return {**result, **row.get("cacheVariables", {})}

            rc = resolve("RcSamplingComputeOnly")
            self.assertEqual(rc["FOC_ADC_RC_DIAGNOSTIC"], "ON")
            self.assertEqual(rc["FOC_ADC_RC_MIN_LOW_ON_TICKS"], "1700")
            self.assertEqual(rc["FOC_ADAPTIVE_FILTER_EXPERIMENT"], "ON")
            self.assertEqual(rc["FOC_ADC_SENSE_TOPOLOGY"], "LOW_SIDE_UV")
            self.assertNotEqual(rc.get("FOC_LATEST_ORIGINAL_FSM"), "ON")
            self.assertNotEqual(rc.get("FOC_COMPACT_CLOSED_LOOP"), "ON")
            motor = resolve("LatestOriginalStartupEvidence")
            self.assertNotEqual(motor.get("FOC_ADC_RC_DIAGNOSTIC"), "ON")

    def test_ab_cmake_gates_and_telemetry_remain_explicit(self):
        for slot in "ab":
            text = (ROOT / f"foc2_app_{slot}/CMakeLists.txt").read_text(encoding="utf-8")
            block = text[text.index("if(FOC_ADC_RC_DIAGNOSTIC)"):
                         text.index("if(FOC_ADC_WINDOW)", text.index("if(FOC_ADC_RC_DIAGNOSTIC)"))]
            for token in ("NOT FOC_ADAPTIVE_FILTER_EXPERIMENT", "FOC_LATEST_ORIGINAL_FSM",
                          "FOC_COMPACT_CLOSED_LOOP", "LOW_SIDE_UV", "LESS 1700", "GREATER 4249"):
                self.assertIn(token, block)
        adapter = (ROOT / "firmware_common/foc_adc_timing_stm32.c").read_text(encoding="utf-8")
        self.assertIn("RC_MIN=%u LATE=%u HW_VERIFIED=0", adapter)

    def test_linked_ab_candidates_are_the_hard_off_profiles(self):
        for slot in "ab":
            build = ROOT / f"foc2_app_{slot}/build/RcSamplingComputeOnly"
            binary = (build / "foc2.bin").read_bytes()
            for marker in (b"ADAPT=1 HARD_OFF=1 DELAY_PAIRS=1",
                           b"RAM ENABLED=1 HARD_OFF=1 DEADLINE_US=50",
                           b"RC_MIN=%u LATE=%u HW_VERIFIED=0"):
                self.assertIn(marker, binary)
            rows = json.loads((build / "compile_commands.json").read_text(encoding="utf-8"))
            command = next(row["command"] for row in rows
                           if row["file"].replace("\\", "/").endswith("/Core/Src/main.c"))
            for flag in ("-DFOC_ADC_RC_DIAGNOSTIC=1", "-DFOC_ADC_SENSE_TOPOLOGY=2",
                         "-DFOC_ADAPTIVE_FILTER_EXPERIMENT=1", "-DFOC_PROTECTED_CLOSED_LOOP=1"):
                self.assertIn(flag, command)
            for flag in ("-DFOC_LATEST_ORIGINAL_FSM=1", "-DFOC_COMPACT_CLOSED_LOOP=1"):
                self.assertNotIn(flag, command)


if __name__ == "__main__":
    unittest.main()
