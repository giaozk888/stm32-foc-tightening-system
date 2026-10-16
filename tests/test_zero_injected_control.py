"""Offline fixture/hash/register/ownership admission tests; no board IO."""
from pathlib import Path
import hashlib
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import zero_injected_control_acceptance as accept
import zero_injected_control_sample as sample

FRESH = ("PROFILE=LOCKED_DIAGNOSTIC ADC_OWNER=1 LOCK=1 SD=0 MOE=0 CCER=0 CEN=0 "
         "FOC=0 MOTOR_READY=0 IF=0 ADC_READY=1 ACTIVE=0 STATE=0 REASON=0 "
         "SPAN=100 NOM=0 U0=0 V0=0 N=0 SET=0 RET=0 ADC=0")


def good_regs():
    values = {a: 0 for a in accept.PATH_ADDRESSES}
    values.update({0x50000308: 0x00480000, 0x40021088: 0x20000000,
                   0x40012C2C: 4249, 0x40012C00: 0x20, 0x40012C04: 0x700000,
                   0x40012C1C: 0x7800, 0x40012C40: 3500,
                   0x50000004: 0x40, 0x50000008: 8, 0x50000014: 0x10,
                   0x5000004C: 0x2A0, 0x50000108: 8, 0x50000114: 0x80,
                   0x5000014C: 0x4A0, 0x48000000: 0xF})
    return values


def render(values):
    return "\n".join(f"0x{a:08X} : {v:08X}" for a, v in values.items())


class InjectedControlTests(unittest.TestCase):
    def handover(self):
        return {"profile": accept.PROFILE, "target_slot": "A", "pass": True,
                "inspect_only": False, "sampling_commands": False,
                "motion_commands": False, "image_sha256": accept.PINNED["A"],
                "physical_drive_off_user_confirmed": True,
                "force_confirm": False, "direct_metadata_write": False,
                "final_flash": {"all_protected_regions_unchanged": True},
                "final_fw": {"CURRENT": "A", "CONFIRMED": "A", "PENDING": "-",
                             "ATTEMPTS": "0", "ACTIVE": "0", "GEN": "403"},
                "three_phase_service": {"zero": dict(x.split("=") for x in FRESH.split())},
                "async_clock_registers": accept.require_injected_registers(render(good_regs()))}

    def test_artifacts_exact_and_still_hard_locked(self):
        for slot in "AB":
            path, image = accept.pinned_image(slot)
            self.assertTrue(path.is_file())
            self.assertEqual(accept.image_info(image)[0], slot)
            self.assertEqual(hashlib.sha256(image).hexdigest(), accept.PINNED[slot])
        with self.assertRaises(ValueError):
            accept.pinned_image("-")

    def test_offline_build_only_injected_zero_not_raw_or_normal_startup(self):
        build = ROOT / "foc2_app_a/build/ZeroInjectedControlOff20261012"
        cache = (build / "CMakeCache.txt").read_text(encoding="utf-8")
        for option in ("ZERO_RETEST_BOOT", "UART_FIRMWARE_TRANSFER"):
            self.assertIn(option + ":BOOL=ON", cache)
        for option in ("ADC_DMA_RAW_DIAGNOSTIC", "ADC_DMA_THREE_PHASE_DIAGNOSTIC",
                       "ADC_DMA_PARALLEL_DIAGNOSTIC", "ADC_DMA_REFERENCE_INPUT_DIAGNOSTIC",
                       "ADC_CONTROL_PINS_LOW_DIAGNOSTIC", "FOC_ISOLATED_CONCURRENCY",
                       "FOC_ADC_WINDOW", "SAFETY_LOCKED_BOOT"):
            self.assertIn(option + ":BOOL=OFF", cache)
        command = next(x for x in __import__("json").loads(
            (build / "compile_commands.json").read_text(encoding="utf-8"))
            if x["file"].replace("\\", "/").endswith("Core/Src/main.c"))["command"]
        self.assertIn("-DZERO_RETEST_BOOT=1", command)
        self.assertNotIn("-DADC_DMA_RAW_DIAGNOSTIC", command)

    def test_complete_injected_registers_required(self):
        accept.require_injected_registers(render(good_regs()))
        for address in accept.PATH_ADDRESSES:
            values = good_regs()
            del values[address]
            with self.subTest(missing=hex(address)), self.assertRaises(RuntimeError):
                accept.require_injected_registers(render(values))

    def test_reject_trigger_sampletime_irq_pin_timer_clock_mismatch(self):
        for address, bad in ((0x50000308, 0x430000), (0x40021088, 0x10000000),
                (0x40012C28, 1), (0x40012C2C, 4248), (0x40012C00, 0x21),
                (0x40012C04, 0), (0x40012C0C, 1), (0x40012C1C, 0x6800),
                (0x40012C40, 3499), (0x50000004, 0x60), (0x50000104, 0x40),
                (0x50000008, 0), (0x50000108, 0), (0x50000014, 0x38),
                (0x50000114, 0x1C0), (0x5000004C, 0x2A1),
                (0x5000014C, 0x2A0), (0x5000000C, 1 << 25),
                (0x5000010C, 1), (0x48000000, 0), (0x4800000C, 1)):
            values = good_regs()
            values[address] = bad
            with self.subTest(address=hex(address)), self.assertRaises(RuntimeError):
                accept.require_injected_registers(render(values))

    def test_fresh_owner_not_old_raw_status(self):
        accept.require_fresh_owner(FRESH)
        for old, new in (("ADC_OWNER=1", "ADC_OWNER=0"), ("STATE=0", "STATE=4"),
                         ("SD=0", "SD=1"), ("ADC=0", "ADC=1")):
            with self.assertRaises(RuntimeError):
                accept.require_fresh_owner(FRESH.replace(old, new))

    def test_handover_exact_a_profile_fallback_and_ownership(self):
        self.assertEqual(sample.require_handover(self.handover()), ("A", 403))
        for key, value in (("profile", "PARALLEL"), ("target_slot", "B"),
                          ("image_sha256", "bad"), ("pass", False),
                          ("inspect_only", True), ("sampling_commands", True),
                          ("physical_drive_off_user_confirmed", False),
                          ("force_confirm", True), ("direct_metadata_write", True)):
            bad = self.handover()
            bad[key] = value
            with self.subTest(key=key), self.assertRaises(RuntimeError):
                sample.require_handover(bad)
        for section, key, value in (("final_flash", "all_protected_regions_unchanged", False),
                                   ("final_fw", "PENDING", "B")):
            bad = self.handover()
            bad[section][key] = value
            with self.assertRaises(RuntimeError): sample.require_handover(bad)
        bad = self.handover()
        bad["three_phase_service"]["zero"]["ADC_OWNER"] = "0"
        with self.assertRaises(RuntimeError): sample.require_handover(bad)

    def test_deployment_baseline_only_b_exact_locked_fallback(self):
        from unittest.mock import patch
        with patch.object(accept, "locked_baseline", return_value={"current": "A"}):
            with self.assertRaises(RuntimeError): accept.diagnostic_baseline(b"")
        with patch.object(accept, "locked_baseline", return_value={"current": "B"}) as check:
            accept.diagnostic_baseline(b"")
            known = check.call_args.kwargs["known"]
            self.assertEqual(known["A"], {accept.RAW_PINNED["A"]})
            self.assertEqual(known["B"], {accept.RAW_PINNED["B"]})


if __name__ == "__main__":
    unittest.main()
