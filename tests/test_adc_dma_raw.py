"""Offline raw CRC/reference and locked-service source contracts; no hardware."""

from app_source_view import read_app_source
import ctypes
from pathlib import Path
import random
import struct
import subprocess
import unittest
import zlib

ROOT = Path(__file__).resolve().parents[1]


class Report(ctypes.Structure):
    _fields_ = [(name, ctypes.c_uint16) for name in ("min_u", "max_u", "min_v", "max_v")] + [
        ("crc32", ctypes.c_uint32)]


class RawReportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        directory = ROOT / "tests/adc_dma_raw_build"
        directory.mkdir(exist_ok=True)
        dll = directory / "adc_raw_report.dll"
        subprocess.run([r"D:\Qt\Tools\mingw1310_64\bin\gcc.exe", "-std=c11", "-O2",
                        "-Wall", "-Wextra", "-Werror", "-pedantic", "-shared",
                        str(ROOT / "firmware_common/adc_raw_report.c"), "-o", str(dll)], check=True)
        cls.dll = ctypes.CDLL(str(dll))
        cls.summarize = cls.dll.AdcRaw_Summarize
        cls.summarize.argtypes = [ctypes.POINTER(ctypes.c_uint16), ctypes.POINTER(ctypes.c_uint16),
                                 ctypes.c_size_t, ctypes.POINTER(Report)]
        cls.summarize.restype = ctypes.c_int

    def test_4096_pairs_match_independent_python_crc_and_min_max(self):
        rng = random.Random(491096)
        for count in (1, 16, 64, 4096):
            for _ in range(12):
                u = [rng.randrange(4096) for _ in range(count)]
                v = [rng.randrange(4096) for _ in range(count)]
                array = ctypes.c_uint16 * count
                report = Report()
                self.assertEqual(self.summarize(array(*u), array(*v), count, ctypes.byref(report)), 1)
                packed = b"".join(struct.pack("<HH", a, b) for a, b in zip(u, v))
                self.assertEqual(report.crc32, zlib.crc32(packed))
                self.assertEqual((report.min_u, report.max_u, report.min_v, report.max_v),
                                 (min(u), max(u), min(v), max(v)))

    def test_invalid_input_does_not_publish_partial_report(self):
        for u, v, count in (([0], [0], 0), ([4096], [0], 1), ([0], [65535], 1)):
            array = ctypes.c_uint16 * len(u)
            report = Report(11, 22, 33, 44, 55)
            self.assertEqual(self.summarize(array(*u), array(*v), count, ctypes.byref(report)), 0)
            self.assertEqual(report.crc32, 55)
        self.assertEqual(self.summarize(None, None, 1, ctypes.byref(Report())), 0)

    def test_extremes_are_retained_not_filtered(self):
        u = (ctypes.c_uint16 * 4)(0, 4095, 1558, 1558)
        v = (ctypes.c_uint16 * 4)(4095, 0, 1558, 1558)
        report = Report()
        self.assertEqual(self.summarize(u, v, 4, ctypes.byref(report)), 1)
        self.assertEqual((report.min_u, report.max_u, report.min_v, report.max_v), (0, 4095, 0, 4095))


class DmaContracts(unittest.TestCase):
    def test_actual_adapter_under_mock_hal(self):
        directory = ROOT / "tests/adc_dma_raw_build"
        directory.mkdir(exist_ok=True)
        exe = directory / "adc_dma_adapter.exe"
        subprocess.run([r"D:\Qt\Tools\mingw1310_64\bin\gcc.exe", "-std=c11", "-O2",
                        "-Wall", "-Wextra", "-Werror", "-pedantic", "-UNDEBUG",
                        "-I", str(ROOT / "tests/adc_dma_mock"),
                        "-I", str(ROOT / "firmware_common"),
                        str(ROOT / "tests/adc_dma_adapter_host.c"),
                        str(ROOT / "firmware_common/adc_raw_report.c"), "-o", str(exe)], check=True)
        # All ten setup HAL calls fail independently, in fresh processes.
        for case in list(range(13)) + list(range(101, 111)) + list(range(211, 217)):
            subprocess.run([str(exe), str(case)], check=True, capture_output=True, text=True)

    def test_module_keeps_bounded_static_independent_capture(self):
        source = (ROOT / "firmware_common/adc_dma_diag.c").read_text(encoding="utf-8")
        for key in ("DMA_NORMAL", "DMA_REQUEST_ADC1", "DMA_REQUEST_ADC2",
                    "ADC_EXTERNALTRIG_T1_TRGO2", "ADC_SAMPLETIME_12CYCLES_5",
                    "DMA_PDATAALIGN_HALFWORD", "DMA_MDATAALIGN_HALFWORD",
                    "ADC_CCR_DUAL", "attempted = 1U", "DMA_IT_HT",
                    "ADC_DMA_DIAG_TIMEOUT_MS", "ADC_FLAG_OVR"):
            self.assertIn(key, source)
        for bad in ("DMA_CIRCULAR", "malloc(", "pvPortMalloc(", "PowerStage_Enable(",
                    "FOC_CurrentLoopStep(", "iu_zero_raw =", "iv_zero_raw ="):
            self.assertNotIn(bad, source)
        start = source[source.index("int AdcDmaDiag_Start"):source.index("void AdcDmaDiag_Complete")]
        self.assertLess(start.index("HAL_ADC_Start_DMA(adcs[1]"), start.index("TIM1->CR1 |= TIM_CR1_CEN"))
        self.assertLess(start.index("HAL_ADC_Start_DMA(adcs[0]"), start.index("TIM1->CR1 |= TIM_CR1_CEN"))
        read = source[source.index("int AdcDmaDiag_Read"):]
        self.assertIn("result.state != ADC_DMA_DIAG_READY", read)
        self.assertIn("index >= ADC_DMA_DIAG_PAIRS", read)

    def test_irqs_never_do_blocking_hal_stop_or_summarize(self):
        source = (ROOT / "firmware_common/adc_dma_diag.c").read_text(encoding="utf-8")
        irq = source[source.index("void AdcDmaDiag_Complete"):source.index("void AdcDmaDiag_Service")]
        for bad in ("HAL_ADC_Stop", "HAL_ADC_Init", "AdcRaw_Summarize", "vTaskDelay", "while ("):
            self.assertNotIn(bad, irq)
        self.assertIn("done_mask == 3U", irq)
        self.assertIn("StopTrigger();", irq)

    def test_maintenance_and_adc_background_blocked_while_capture_active(self):
        source = (ROOT / "firmware_common/zero_retest_boot.inc").read_text(encoding="utf-8")
        owner = (ROOT / "firmware_common/zero_adc_owner.inc").read_text(encoding="utf-8")
        admission = owner[owner.index("static uint8_t ZeroAdcOwner_Admitted"):
                          owner.index("static void ZeroAdcOwner_Service")]
        self.assertIn("adc_fault", admission)
        self.assertIn("AdcDmaDiag_Busy()", admission)
        self.assertIn("BootHealth_IsCurrentTrial() || fw_update.active", admission)
        self.assertIn("bus_mv < 10000U || bus_mv > 14000U", owner)
        self.assertIn("No background PC4/PC5 reconfiguration during capture", source)
        busy = source[source.index("ZeroAdcOwner_Service();"):
                      source.index("now = HAL_GetTick(); /* Request handling")]
        self.assertIn("if (AdcDmaDiag_Busy())", busy)
        self.assertIn("continue;", busy)
        self.assertIn("(void)ZeroAdcOwner_LiveSample();", source)
        console = (ROOT / "firmware_common/adc_dma_diag_console.inc").read_text(encoding="utf-8")
        self.assertIn("ZeroRetest_SubmitAcquisition(request_id, ZERO_ADC_ACQUIRE_DMA);", console)
        self.assertNotIn("ADC_AnalogLiveSample(", console)
        self.assertNotIn("AdcDmaDiag_Start(", console)
        self.assertIn("ADC_DMA_SAMPLING_ACTIVE", console)
        self.assertIn("first % 16U", console)
        self.assertIn("AdcDmaDiag_Read", console)

    def test_feature_cannot_be_enabled_in_a_normal_motor_build(self):
        for slot in "ab":
            cmake = (ROOT / f"foc2_app_{slot}/CMakeLists.txt").read_text(encoding="utf-8")
            self.assertIn("ADC_DMA_RAW_DIAGNOSTIC AND NOT ZERO_RETEST_BOOT", cmake)
            main = read_app_source(ROOT / f"foc2_app_{slot}/Core/Src/main.c",encoding="utf-8")
            self.assertIn("AdcDmaDiag_Error(hadc);", main)


if __name__ == "__main__":
    unittest.main()
