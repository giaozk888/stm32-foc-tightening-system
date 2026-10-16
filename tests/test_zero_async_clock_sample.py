"""Offline handover/fresh-boot contracts, never accesses a serial port."""
from copy import deepcopy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import zero_async_clock_sample as sample

FRESH = ("OK PROFILE=LOCKED_DIAGNOSTIC LOCK=1 SD=0 MOE=0 CCER=0 CEN=0 "
         "FOC=0 MOTOR_READY=0 IF=0 ADC_READY=1 ACTIVE=0 STATE=0 REASON=0 "
         "SPAN=100 NOM=0 U0=0 V0=0 N=0 SET=0 ADC=0")


class AsyncSampleTests(unittest.TestCase):
    def handover(self, slot="B"):
        return {"pass": True, "inspect_only": False, "target_slot": slot,
                "image_sha256": sample.PINNED[slot], "sampling_commands": False,
                "motion_commands": False,
                "final_flash": {"all_protected_regions_unchanged": True},
                "async_clock_registers": {},
                "final_fw": {"CURRENT": slot, "CONFIRMED": slot, "PENDING": "-",
                             "ATTEMPTS": "0", "ACTIVE": "0", "GEN": "361"}}

    def test_exact_normal_deployment_handover_required(self):
        for slot in "AB":
            record = self.handover(slot)
            self.assertEqual(sample.require_handover(record), (slot, 361))
            for key, value in (("pass", False), ("inspect_only", True),
                               ("image_sha256", "bad"), ("sampling_commands", True),
                               ("motion_commands", True), ("target_slot", "-")):
                broken = deepcopy(record)
                broken[key] = value
                with self.assertRaises(RuntimeError):
                    sample.require_handover(broken)
            for key, value in (("PENDING", "A"), ("ATTEMPTS", "1"),
                               ("CURRENT", "-"), ("ACTIVE", "1")):
                broken = deepcopy(record)
                broken["final_fw"][key] = value
                with self.assertRaises(RuntimeError):
                    sample.require_handover(broken)

    def test_fresh_unsampled_and_locked_before_acquisition(self):
        sample.require_fresh_boot(FRESH)
        for key, value in (("STATE", "4"), ("REASON", "2"), ("ADC", "1"),
                           ("SET", "1"), ("N", "1"), ("U0", "1"), ("V0", "1"),
                           ("SPAN", "20"), ("SD", "1"), ("MOE", "1")):
            old = next(token for token in FRESH.split() if token.startswith(key + "="))
            with self.assertRaises(RuntimeError):
                sample.require_fresh_boot(FRESH.replace(old, key + "=" + value))

    def test_one_shot_only_and_no_reset_motion_or_unlock(self):
        source = Path(sample.__file__).read_text(encoding="utf-8")
        self.assertEqual(source.count("uart.sample_once()"), 1)
        for forbidden in ('"-rst"', '"START"', '"CLEAR"', '"FW END"',
                          '"FW CONFIRM"', '"BOOT A"', '"BOOT B"'):
            self.assertNotIn(forbidden, source)
        self.assertLess(source.index('result["before_hardware"] = read_hardware()'),
                        source.index("uart.sample_once()"))
        self.assertIn('result["after_hardware"] = read_hardware()', source)


if __name__ == "__main__":
    unittest.main()
