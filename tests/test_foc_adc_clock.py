"""Offline source contracts for the ES0430 async ADC1/2 clock change."""
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]


class AdcClockTests(unittest.TestCase):
    def test_shared_policy_preserves_frequency_and_checks_both_fields(self):
        text = (ROOT / "firmware_common/foc_adc_clock_stm32.h").read_text(encoding="utf-8")
        self.assertIn("FOC_ADC_CLOCK_SOURCE RCC_ADC12CLKSOURCE_SYSCLK", text)
        self.assertIn("FOC_ADC_CLOCK_PRESCALER ADC_CLOCK_ASYNC_DIV4", text)
        self.assertIn("FOC_ADC_KERNEL_HZ 170000000U", text)
        self.assertIn("FOC_ADC_KERNEL_HZ / 4U", text)
        self.assertIn("ADC_CCR_CKMODE | ADC_CCR_PRESC", text)
        self.assertIn("__HAL_RCC_GET_ADC12_SOURCE() == FOC_ADC_CLOCK_SOURCE", text)
        self.assertIn("HAL_RCC_GetSysClockFreq() == FOC_ADC_KERNEL_HZ", text)
        self.assertNotIn("MODIFY_REG", text)
        self.assertNotIn("HAL_RCCEx_PeriphCLKConfig", text)

    def test_both_apps_and_msp_use_the_same_policy(self):
        for slot in "ab":
            app = ROOT / f"foc2_app_{slot}"
            main = (app / "Core/Src/main.c").read_text(encoding="utf-8")
            msp = (app / "Core/Src/stm32g4xx_hal_msp.c").read_text(encoding="utf-8")
            for adc in (1, 2):
                self.assertIn(f"hadc{adc}.Init.ClockPrescaler = FOC_ADC_CLOCK_PRESCALER;", main)
            self.assertNotIn("ADC_CLOCK_SYNC_PCLK_DIV4", main)
            self.assertEqual(msp.count("PeriphClkInit.Adc12ClockSelection = FOC_ADC_CLOCK_SOURCE;"), 2)
            configure = re.search(r"static HAL_StatusTypeDef ADC_ConfigIndependentSameTrigger\(void\)\n\{.*?\n\}", main, re.S)[0]
            self.assertLess(configure.index("!FocAdcClock_IsExpected()"), configure.index("HAL_ADCEx_MultiModeConfigChannel"))
            self.assertIn("ADC_EXTERNALTRIGINJEC_T1_TRGO2", configure)
            self.assertIn("ADC_SAMPLETIME_12CYCLES_5", configure)
            self.assertIn("htim1.Init.Prescaler = 0;", main)
            self.assertIn("htim1.Init.Period = 4249;", main)

    def test_cubemx_settings_record_async_prescaler(self):
        for slot in "ab":
            rows = dict(line.split("=", 1) for line in
                        (ROOT / f"foc2_app_{slot}/foc2.ioc").read_text(encoding="utf-8").splitlines()
                        if "=" in line)
            for adc in (1, 2):
                self.assertEqual(rows[f"ADC{adc}.ClockPrescaler"], "ADC_CLOCK_ASYNC_DIV4")
                self.assertIn("ClockPrescaler", rows[f"ADC{adc}.IPParameters"].split(","))

    def test_zero_sample_rechecks_clock_without_relaxing_quality_gates(self):
        text = (ROOT / "firmware_common/zero_retest_boot.inc").read_text(encoding="utf-8")
        sample = text[text.index('if (strcmp(cmd, "ZERO SAMPLE")'):]
        # ADC ownership moved from ProtocolTask into the dedicated owner. The
        # console must submit, not configure/poll ADC2 directly.
        self.assertIn("ZeroRetest_SubmitAcquisition(request_id, ZERO_ADC_ACQUIRE_ZERO)", sample)
        self.assertNotIn("ADC_AnalogLiveSample()", sample)
        owner = (ROOT / "firmware_common/zero_adc_owner.inc").read_text(encoding="utf-8")
        admission = owner[owner.index("static uint8_t ZeroAdcOwner_Admitted"):
                          owner.index("static void ZeroAdcOwner_Service")]
        self.assertIn("!FocAdcClock_IsExpected()", admission)
        self.assertIn("zero_retest_attempted", admission)
        self.assertIn("ZeroRetest_Locked()", admission)
        service = owner[owner.index("static void ZeroAdcOwner_Service"):
                        owner.index("static void ZeroRetest_SubmitAcquisition")]
        self.assertLess(service.index("ZeroAdcOwner_Admitted(request.kind)"),
                        service.index("ZeroAdcOwner_LiveSample()"))
        self.assertGreaterEqual(service.count("ZeroAdcOwner_Admitted(request.kind)"), 2)
        header = (ROOT / "firmware_common/foc_current_zero.h").read_text(encoding="utf-8")
        for gate in ("MAX_SPAN = 100U", "MAX_NOMINAL_DELTA = 100U", "WINDOW_PAIRS = 4000U",
                     "MAX_HALF_DRIFT = 5U", "SETTLE_PAIRS = 20000U"):
            self.assertIn(gate, header)

    def test_window_adapter_uses_shared_live_clock_guard(self):
        text = (ROOT / "firmware_common/foc_adc_timing_stm32.c").read_text(encoding="utf-8")
        guard = text[text.index("static int TimerGeometryReady"):text.index("int FocAdcTiming_PairReady")]
        self.assertIn("FocAdcClock_IsExpected()", guard)
        self.assertIn("TIM1->PSC == 0U", guard)
        self.assertIn("FOC_ADC_SENSE_TOPOLOGY != 0", guard)

    def test_async_window_covers_injected_abort_latency(self):
        header = (ROOT / "firmware_common/foc_adc_timing_stm32.h").read_text(encoding="utf-8")
        source = (ROOT / "firmware_common/foc_adc_timing_stm32.c").read_text(encoding="utf-8")
        self.assertIn("FOC_ADC_TRIGGER_LATENCY_MAX_TICKS 14U", header)
        self.assertIn("FOC_ADC_TRIGGER_LATENCY_MAX_TICKS, 50U", source)
        self.assertNotIn("FOC_ADC_SETTLE_TICKS, 8U", source)


if __name__ == "__main__":
    unittest.main()
