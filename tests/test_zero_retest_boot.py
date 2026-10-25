"""Offline contracts for the two-slot locked diagnostic profile."""

from app_source_view import read_app_source
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

class LockedProfileTests(unittest.TestCase):
    def test_both_slot_startups_divert_before_normal_initialization(self):
        for slot in "ab":
            text = read_app_source(ROOT / f"foc2_app_{slot}/Core/Src/main.c",encoding="utf-8")
            start = text[text.index("static void StartupTask(void *argument)\n{"):]
            self.assertLess(start.index("ZeroRetest_RunForever();"), start.index("PW_Kvs_Init()"))
            self.assertLess(start.index("ZeroRetest_RunForever();"), start.index("PWM_StartAll();"))
            callback = text[text.index("void HAL_ADCEx_InjectedConvCpltCallback"):]
            self.assertLess(callback.index("ZeroRetest_InjectedPair();"), callback.index("FOC_CurrentLoopStep"))
            for name in ("PowerStage_Enable", "PWM_StartAll", "PWM_SetDuty"):
                function = re.search(r"static void " + name + r"\([^;]*?\)\n\{.*?\n\}", text, re.S)[0]
                self.assertIn("#if defined(ZERO_RETEST_BOOT)", function)
                self.assertIn("return;", function.split("#endif")[0])

    def test_no_motor_or_storage_or_network_initialization(self):
        text = (ROOT / "firmware_common/zero_retest_boot.inc").read_text(encoding="utf-8")
        text += (ROOT / "firmware_common/zero_adc_owner.inc").read_text(encoding="utf-8")
        for bad in ("PowerStage_Enable(", "PWM_StartAll(", "MotorControlTask,", "TighteningTask,",
                    "ModbusTask,", "AS5047P_", "PW_Kvs_Init", "TightenParams_Save", "EspLink_Init"):
            self.assertNotIn(bad, text)
        self.assertIn("motor NOT qualified", text)
        self.assertIn("NOT zero/FOC pass", text)
        self.assertIn("if (!protocol_esp_ping_uart_local)", text)
        self.assertIn("ZERO_DIAGNOSTIC_COMMAND_ONLY", text)

    def test_sample_is_explicit_supply_gated_and_bounded(self):
        text = (ROOT / "firmware_common/zero_retest_boot.inc").read_text(encoding="utf-8")
        text += (ROOT / "firmware_common/zero_adc_owner.inc").read_text(encoding="utf-8")
        self.assertIn('strcmp(cmd, "ZERO SAMPLE")', text)
        self.assertIn("zero_retest_attempted", text)
        self.assertIn("bus_mv < 10000U || bus_mv > 14000U", text)
        self.assertIn("BootHealth_IsCurrentTrial() || fw_update.active", text)
        self.assertIn("FOC_ZERO_TIMEOUT_MS", text)
        self.assertIn("No filtering or FOC call", text)
        self.assertNotIn("iu_zero_raw =", text)  # diagnostic never publishes motor offsets
        header = (ROOT / "firmware_common/foc_current_zero.h").read_text(encoding="utf-8")
        self.assertIn("FOC_ZERO_MAX_SPAN = 100U", header)
        self.assertIn("FOC_ZERO_WINDOW_PAIRS = 4000U", header)
        self.assertIn("FOC_ZERO_MAX_HALF_DRIFT = 5U", header)
        self.assertIn("FOC_ZERO_MAX_NOMINAL_DELTA = 100U", header)
        self.assertIn("FOC_ZERO_MAX_RESTARTS = 8U", header)
        self.assertIn("FOC_ZERO_TIMEOUT_MS = 5000U", header)
        self.assertIn("SPAN=%u", text)
        self.assertIn("(unsigned)FOC_ZERO_MAX_SPAN", text)

    def test_confirmation_is_independent_fresh_console_service_health(self):
        text = (ROOT / "firmware_common/zero_retest_boot.inc").read_text(encoding="utf-8")
        self.assertIn("stable >= 5000U", text)
        self.assertIn("zero_retest_heartbeats >= 2U", text)
        self.assertIn("now - zero_retest_last_request) < 1500U", text)
        self.assertIn("!zero_retest_interlock_fault", text)
        self.assertIn("!foc_control_count", text)
        self.assertIn("elapsed >= 12000U", text)
        for slot in "ab":
            cmake = (ROOT / f"foc2_app_{slot}/CMakeLists.txt").read_text(encoding="utf-8")
            self.assertIn("ZERO_RETEST_BOOT is a standalone", cmake)

if __name__ == "__main__":
    unittest.main()
