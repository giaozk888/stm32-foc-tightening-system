"""Offline source contracts; never accesses a serial port or probe."""
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]

def without_test_profiles(text):
    """Select only these two opt-in branches OFF; retain other guards verbatim.

    Compare both old and new source under the same selection. Unknown/nested
    guards remain byte-for-byte intact; malformed nesting fails the test.
    """
    stack, output, emit = [], [], True
    for row in text.splitlines(keepends=True):
        directive = re.sub(r"/\*.*?\*/|//.*", "", row).strip()
        if re.match(r"#\s*(if|ifdef|ifndef)\b", directive):
            target = directive in ("#if defined(TIGHTEN_SYNTHETIC_BENCH)",
                                   "#if defined(FOC_ISOLATED_CONCURRENCY)")
            stack.append((target, emit))
            if target:
                emit = False
            elif emit:
                output.append(row)
        elif directive == "#else":
            if not stack:
                raise ValueError("Unmatched else")
            target, parent = stack[-1]
            if target:
                emit = parent and not emit
            elif emit:
                output.append(row)
        elif directive == "#endif":
            if not stack:
                raise ValueError("Unmatched endif")
            target, parent = stack.pop()
            if not target and emit:
                output.append(row)
            emit = parent
        elif re.match(r"#\s*elif\b", directive):
            if not stack or stack[-1][0]:
                raise ValueError("Unsupported selected elif")
            if emit:
                output.append(row)
        elif emit:
            output.append(row)
    if stack:
        raise ValueError("Unclosed guard")
    return "".join(output)

class StableZeroIntegration(unittest.TestCase):
    def test_profile_selector_nested_and_fail_closed(self):
        text = "a\n#if defined(FOC_ISOLATED_CONCURRENCY)\nx\n#if OTHER\ny\n#endif\n#else\n#if KEEP\nb\n#endif\n#endif\nz\n"
        self.assertEqual(without_test_profiles(text), "a\n#if KEEP\nb\n#endif\nz\n")
        self.assertEqual(without_test_profiles("#if KEEP\na\n#endif /* KEEP */\n"),
                         "#if KEEP\na\n#endif /* KEEP */\n")
        for bad in ("#endif\n", "#else\n", "#if OTHER\na\n",
                    "#if defined(FOC_ISOLATED_CONCURRENCY)\n#elif X\n#endif\n"):
            with self.assertRaises(ValueError):
                without_test_profiles(bad)

    def test_raw_unfiltered_calibration_precedes_controller(self):
        for slot in "ab":
            source = (ROOT / f"foc2_app_{slot}/Core/Src/main.c").read_text(encoding="utf-8")
            self.assertNotIn("IsolatedBench_DigitalBaseline", source)
            callback = re.search(r"void HAL_ADCEx_InjectedConvCpltCallback.*?\n}\n", source, re.S)[0]
            self.assertLess(callback.index("IsolatedZero_Feed(u, v)"), callback.index("current_filter_enable != 0U"))
            self.assertLess(callback.index("IsolatedZero_Feed(u, v)"), callback.index("FOC_CurrentLoopStep"))
            self.assertIn("if (IsolatedZero_Feed(u, v)) return;", callback)
            self.assertIn("IsolatedZero_Wait();", source)
            self.assertIn("seq_delta < 1800U || seq_delta > 2200U", source)
            self.assertIn('strcmp(cmd, "BENCH ZERO")', source)
            self.assertRegex(source, r"#define\s+FOC_CURRENT_TRIP_A\s+4\.0f")

    def test_foreground_snapshots_and_no_isr_blocking(self):
        port = (ROOT / "firmware_common/isolated_concurrency.inc").read_text(encoding="utf-8")
        feed = port[port.index("static int IsolatedZero_Feed"):port.index("static void IsolatedZero_Snapshot")]
        for forbidden in ("while (", "for (", "UART_", "vTaskDelay", "Malloc", "DmaStop", "IsolatedBench_Stop("):
            self.assertNotIn(forbidden, feed)
        self.assertIn("if (!IsolatedBench_Locked())", feed)
        self.assertIn("FOC_ZERO_READY", feed)
        self.assertIn("current_filter_enable = run_zero_cal_done = 1U", feed)
        active = port[port.index("static int IsolatedBench_Active"):port.index("static int IsolatedBench_Locked")]
        self.assertIn("isolated_zero_ready != 0U", active)
        snapshot = port[port.index("static void IsolatedZero_Snapshot"):port.index("static void IsolatedZero_Format")]
        self.assertLess(snapshot.index("__disable_irq()"), snapshot.index("FocZero_Snapshot"))
        self.assertIn("__set_PRIMASK(mask)", snapshot)

    def test_failure_keeps_power_closed_and_no_forced_health(self):
        port = (ROOT / "firmware_common/isolated_concurrency.inc").read_text(encoding="utf-8")
        fail = port[port.index("static void IsolatedZero_Fail"):port.index("static int IsolatedBench_Active")]
        for guard in ("~TIM_CR1_CEN", "TIM1->CCER = 0U", "~(TIM_BDTR_MOE | TIM_BDTR_AOE)",
                      "foc_fault = 1U", "run_zero_cal_done = 0U", "FOC_FAULT_STARTUP_ZERO_CAL"):
            self.assertIn(guard, fail)
        for forbidden in ("PowerStage_Enable", "GPIO_PIN_SET", "FW CONFIRM", "BootMeta_Write"):
            self.assertNotIn(forbidden, port)
        self.assertIn("FOC_ZERO_TIMEOUT_MS", port)
        self.assertIn("isolated_zero_shutdown_pending", port)

    def test_no_heap_or_wait_in_core_feed(self):
        source = (ROOT / "firmware_common/foc_current_zero.c").read_text(encoding="utf-8")
        feed = source[source.index("void FocZero_Push"):source.index("void FocZero_Snapshot")]
        for forbidden in ("malloc", "while (", "for (", "memcpy", "memset", "HAL_", "vTask", "float "):
            self.assertNotIn(forbidden, feed)
        self.assertIn("Discard the WHOLE contaminated window", feed)
        self.assertIn("FOC_ZERO_MAX_HALF_DRIFT", feed)
        self.assertIn("FOC_ZERO_MAX_NOMINAL_DELTA", feed)

if __name__ == "__main__":
    unittest.main()
