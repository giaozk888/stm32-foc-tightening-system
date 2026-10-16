"""Offline guard tests for the single bounded UART speed check."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from motor_motion_smoke import (
    BOUNDS, HOST_STOP_SECONDS, TARGET_RPM_RANGE, bounded_recipe, require_idle_ready,
)
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "simulation/tightening"))
from model import load_firmware_profile


class FakeBoard:
    def __init__(self):
        self.replies = {
            "FW STATUS": "1 OK FW CURRENT=B CONFIRMED=B PENDING=- ACTIVE=0 ATTEMPTS=0",
            "SELFTEST STATUS": "1 OK SELFTEST READY=1 MASK=0x000",
            "STATUS": "1 OK STATUS MODE=IDLE BUSY=0 FLT=0 POS=0.00deg CTRL=0.0rpm",
            "ANALOG SAFE STATUS": "1 OK SAFE LATCHED=0 SD=1 MOE=1 FOC=1",
        }

    def command(self, command):
        return self.replies[command]  # Unexpected write commands fail the test.


class MotorGuardTest(unittest.TestCase):
    def test_generic_confirmed_b(self):
        self.assertIn("MODE=IDLE", require_idle_ready(FakeBoard(), "B"))

    def test_wrong_expected_slot_rejected(self):
        with self.assertRaises(RuntimeError):
            require_idle_ready(FakeBoard(), "A")

    def test_fault_trial_busy_and_zero_cal_rejected(self):
        for command, old, bad in (
                ("FW STATUS", "PENDING=-", "PENDING=B"),
                ("FW STATUS", "ACTIVE=0", "ACTIVE=1"),
                ("SELFTEST STATUS", "READY=1", "READY=0"),
                ("STATUS", "FLT=0", "FLT=1"),
                ("STATUS", "BUSY=0", "BUSY=1"),
                ("ANALOG SAFE STATUS", "LATCHED=0", "LATCHED=1")):
            board = FakeBoard()
            board.replies[command] = board.replies[command].replace(old, bad)
            with self.subTest(bad=bad), self.assertRaises(RuntimeError):
                require_idle_ready(board, "B")

    def test_on_board_rundown_timeout_and_target(self):
        self.assertEqual(BOUNDS["RUNDOWN_RPM"], 80)
        self.assertEqual(BOUNDS["RUNDOWN_TIMEOUT_MS"], 1000)
        self.assertEqual(BOUNDS["MAX_TRAVEL_DEG"], 100)
        self.assertEqual(HOST_STOP_SECONDS, 0.4)
        # A 400 ms host stop should precede contact transition, so this is not
        # a tightening/torque-stage test. Existing parameter range is retained.
        self.assertGreaterEqual(BOUNDS["CONTACT_MS"], 1000)

    def test_test_target_matches_source_recipe_default(self):
        # Read the explicit normal branch after the opt-in X2 header split;
        # numeric-only X() matching no longer represents the source contract.
        profile = load_firmware_profile(speed_profile="baseline")
        low, high = profile.ranges["rundown_rpm"]
        default = profile.recipe["rundown_rpm"]
        self.assertEqual(BOUNDS["RUNDOWN_RPM"], default)
        self.assertGreaterEqual(BOUNDS["RUNDOWN_RPM"], low)
        self.assertLessEqual(BOUNDS["RUNDOWN_RPM"], high)
        self.assertEqual(TARGET_RPM_RANGE, (low, high))

    def test_107_changes_only_target_without_widening_limits(self):
        bounds = bounded_recipe(107)
        self.assertEqual(bounds["RUNDOWN_RPM"], 107)
        self.assertEqual({k: v for k, v in bounds.items() if k != "RUNDOWN_RPM"},
                         {k: v for k, v in BOUNDS.items() if k != "RUNDOWN_RPM"})
        self.assertEqual(BOUNDS["RUNDOWN_RPM"], 80)
        self.assertEqual(HOST_STOP_SECONDS, 0.4)

    def test_out_of_normal_range_is_rejected(self):
        for value in (0, 19, 121, 160, 250):
            with self.subTest(target=value), self.assertRaises(ValueError):
                bounded_recipe(value)


if __name__ == "__main__":
    unittest.main()
