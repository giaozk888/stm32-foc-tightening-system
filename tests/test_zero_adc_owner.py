"""Actual C owner/queues under mocks; no board IO or torque qualification."""
from pathlib import Path
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]
GCC = r"D:\Qt\Tools\mingw1310_64\bin\gcc.exe"


class AdcOwnerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        directory = ROOT / "tests/zero_adc_owner_build"
        directory.mkdir(exist_ok=True)
        cls.executables = {}
        profiles = {
            "zero": [],
            "uv_dma": ["ADC_DMA_RAW_DIAGNOSTIC"],
            "uvw_sequential": ["ADC_DMA_RAW_DIAGNOSTIC", "ADC_DMA_THREE_PHASE_DIAGNOSTIC"],
            "uvw_parallel": ["ADC_DMA_RAW_DIAGNOSTIC", "ADC_DMA_THREE_PHASE_DIAGNOSTIC",
                             "ADC_DMA_PARALLEL_DIAGNOSTIC"],
        }
        for name, flags in profiles.items():
            target = directory / (name + ".exe")
            subprocess.run([GCC, "-std=c11", "-O2", "-Wall", "-Wextra", "-Werror",
                            "-pedantic", "-UNDEBUG", *["-D" + flag for flag in flags],
                            str(ROOT / "tests/zero_adc_owner_host.c"),
                            str(ROOT / "firmware_common/foc_current_zero.c"),
                            "-o", str(target)], check=True)
            cls.executables[name] = target

    def test_actual_owner_c_in_all_profiles(self):
        for name, executable in self.executables.items():
            for case in range(43):
                with self.subTest(profile=name, scenario=case):
                    subprocess.run([str(executable), str(case)], check=True,
                                   capture_output=True, text=True)

    def test_console_never_operates_adc2_or_starts_dma_directly(self):
        for name in ("adc_parallel_console.inc", "adc_three_phase_console.inc",
                     "adc_dma_diag_console.inc"):
            source = (ROOT / "firmware_common" / name).read_text(encoding="utf-8")
            self.assertIn("ZeroRetest_SubmitAcquisition", source)
            self.assertNotIn("ADC_AnalogLiveSample(", source)
            self.assertNotIn("AdcDmaDiag_Start(", source)
        boot = (ROOT / "firmware_common/zero_retest_boot.inc").read_text(encoding="utf-8")
        self.assertNotIn("ADC_AnalogLiveSample(", boot)
        self.assertIn("ZeroAdcOwner_LiveSample();", boot)
        self.assertLess(boot.index("ZeroAdcOwner_Init();"), boot.index("xTaskCreate(ProtocolTask"))
        self.assertLess(boot.index("ZeroAdcOwner_Service();"), boot.index("if (AdcDmaDiag_Busy())"))
        self.assertLess(boot.index("if (AdcDmaDiag_Busy())"), boot.index("ZeroAdcOwner_LiveSample();"))
        self.assertIn("now = HAL_GetTick(); /* Request handling", boot)
        self.assertIn("ADC_OWNER=1", boot)

    def test_owner_retains_gate_snapshot_and_does_not_reply_from_other_task(self):
        owner = (ROOT / "firmware_common/zero_adc_owner.inc").read_text(encoding="utf-8")
        service = owner.split("static void ZeroAdcOwner_Service(void)", 1)[1].split(
            "static void ZeroRetest_SubmitAcquisition", 1)[0]
        self.assertNotIn("Protocol_Send", service)
        self.assertIn("bus_mv < 10000U || bus_mv > 14000U", service)
        self.assertIn("reply.pc4_raw * reply.vdda_mv", service)
        self.assertIn("ZeroAdcOwner_Admitted(request.kind)", service)
        self.assertIn("SUPPLY_VALID=%u", owner)
        self.assertIn("xQueueCreateStatic", owner)
        self.assertNotIn("malloc(", owner)


if __name__ == "__main__":
    unittest.main()
