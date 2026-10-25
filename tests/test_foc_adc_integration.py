"""Source-contract audit, not a hardware test."""

from app_source_view import read_app_source
import json
from pathlib import Path
import re
import unittest
ROOT = Path(__file__).resolve().parents[1]


class IntegrationTest(unittest.TestCase):
    def test_default_paths_unchanged(self):
        for slot in "ab":
            root = ROOT / f"foc2_app_{slot}"
            source = read_app_source(root / "Core/Src/main.c",encoding="utf-8")
            self.assertRegex(source, r"#define\s+FOC_VOLTAGE_LIMIT_V\s+0\.80f")
            self.assertIn("HAL_ADCEx_InjectedStart(&hadc2)", source)
            self.assertNotIn("HAL_ADCEx_InjectedStart_IT(&hadc2)", source)
            # The opt-in feedback binding and legacy branch each have a call;
            # the binding returns before the legacy call. Protected dispatch
            # lives in its shared early-ack entry, audited separately.
            self.assertEqual(source.count("FOC_CurrentLoopStep(iu_inj_raw, iv_inj_raw, u, v)"), 2)
            binding = source[source.index('#if defined(FOC_FEEDBACK_SAFETY_BINDING)\n        /* Single filtering'):
                             source.index('/*\n         * PWM-on zero calibration')]
            self.assertIn('FocFeedbackBinding_WorkEnd(feedback_start_us);\n        return;', binding)
            cmake = (root / "CMakeLists.txt").read_text(encoding="utf-8")
            self.assertRegex(cmake, r'option\(FOC_ADC_WINDOW\s+"[^"]+"\s+OFF\)')
            presets = json.loads((root / "CMakePresets.json").read_text(encoding="utf-8"))
            new = next(p for p in presets["configurePresets"] if p["name"] == "FocSamplingReadOnly")
            self.assertEqual(new["cacheVariables"]["FOC_ADC_SENSE_TOPOLOGY"], "UNCONFIRMED")

    def test_atomic_preload_and_no_running_ug(self):
        source = (ROOT / "firmware_common/foc_adc_timing_stm32.c").read_text(encoding="utf-8")
        # Audit the production four-register commit, not the separately
        # guarded hard-off diagnostic's earlier three-register write group.
        commit = source[source.index("void FocAdcTiming_CommitPrepared"):
                        source.index("int FocAdcTiming_RcActuationReady")]
        begin = commit.index("TIM1->CR1 |= TIM_CR1_UDIS")
        end = commit.index("TIM1->CR1 &= ~TIM_CR1_UDIS")
        for ch in range(1, 5):
            self.assertTrue(begin < commit.index(f"TIM1->CCR{ch} =") < end)
        self.assertIn("(TIM1->CR1 & TIM_CR1_CEN) == 0U && udis == 0U", source)
        for slot in "ab":
            hal = (ROOT / f"foc2_app_{slot}/Drivers/STM32G4xx_HAL_Driver/Src/stm32g4xx_hal_tim.c").read_text(encoding="utf-8")
            for preload in ("OC1PE", "OC2PE", "OC3PE", "OC4PE"):
                self.assertIn(preload, hal)

    def test_fail_closed_and_no_isr_busy_wait(self):
        for slot in "ab":
            source = read_app_source(ROOT / f"foc2_app_{slot}/Core/Src/main.c",encoding="utf-8")
            callback = re.search(r"void HAL_ADCEx_InjectedConvCpltCallback.*?\n}\n", source, re.S)[0]
            self.assertLess(callback.index("FocAdcTiming_PairReady"), callback.index("HAL_ADCEx_InjectedGetValue"))
            self.assertIn("__HAL_ADC_DISABLE_IT(&hadc1, ADC_IT_JEOS | ADC_IT_JEOC)", callback)
            self.assertNotIn("while (", callback)
            self.assertNotIn("HAL_Delay", callback)
            self.assertNotIn("UART_Send", callback)

    def test_raw_processing_is_foreground_only(self):
        source = (ROOT / "firmware_common/foc_adc_timing_stm32.c").read_text(encoding="utf-8")
        record = source[source.index("void FocAdcTiming_RecordRaw"):source.index("int FocAdcTiming_ProcessRawOne")]
        for forbidden in ("FocRawSpread_Push", "FocRawSpread_Reset", "memcpy", "memset", "for (", "while ("):
            self.assertNotIn(forbidden, record)
        self.assertIn("FocRawBuffer_Push", record)
        process = source[source.index("int FocAdcTiming_ProcessRawOne"):source.index("void FocAdcTiming_NoteWorkerStack")]
        self.assertIn("__get_IPSR() != 0U", process)
        self.assertIn("__get_PRIMASK() != 0U", process)
        self.assertIn("FocRawSpread_Push", process)
        self.assertIn("FocRawBuffer_Release", process)
        for slot in "ab":
            main = read_app_source(ROOT / f"foc2_app_{slot}/Core/Src/main.c",encoding="utf-8")
            self.assertLess(main.index("FocAdcStatisticsTask_Start()"), main.index("HAL_ADCEx_InjectedStart(&hadc2)"))
            self.assertIn('strcmp(cmd, "ADC BUFFER")', main)
            callback = re.search(r"void HAL_ADCEx_InjectedConvCpltCallback.*?\n}\n", main, re.S)[0]
            self.assertNotIn("ProcessRawOne", callback)
            self.assertIn("FOC_CurrentLoopStep(iu_inj_raw, iv_inj_raw, u, v)", callback)

    def test_raw_producer_no_wait_rmw_or_full_block_copy(self):
        source = (ROOT / "firmware_common/foc_adc_raw_buffer.c").read_text(encoding="utf-8")
        producer = source[source.index("void FocRawBuffer_Push"):source.index("int FocRawBuffer_Acquire")]
        for forbidden in ("for (", "while (", "memcpy", "memset", "atomic_fetch", "atomic_exchange", "atomic_compare"):
            self.assertNotIn(forbidden, producer)
        self.assertIn("memory_order_release", producer)
        self.assertIn("memory_order_acquire", producer)
        self.assertIn("ATOMIC_INT_LOCK_FREE == 2", source)
        consumer = source[source.index("int FocRawBuffer_Acquire"):source.index("void FocRawBuffer_Release")]
        # Acquiring one READY publication must re-read a previously missed
        # other slot: the producer can complete both between the first loads.
        self.assertEqual(consumer.count("atomic_load_explicit(&q->state[0]"), 2)
        self.assertEqual(consumer.count("atomic_load_explicit(&q->state[1]"), 2)

    def test_static_low_priority_worker_bounded(self):
        source = (ROOT / "firmware_common/foc_adc_statistics_task.c").read_text(encoding="utf-8")
        self.assertIn("xTaskCreateStatic", source)
        self.assertNotIn("pvPortMalloc", source)
        self.assertIn("NULL, 1U, statistics_stack", source)
        self.assertEqual(source.count("FocAdcTiming_ProcessRawOne();"), 2)
        self.assertIn("vTaskDelay", source)


if __name__ == "__main__":
    unittest.main()
