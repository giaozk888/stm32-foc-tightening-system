"""Pure offline tests for pinned ADC-owner deployment and one-shot guards."""
import copy
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
import zlib

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import adc_owner_acceptance as deploy
import adc_owner_sample as sample
import adc_parallel_acceptance as old
import zero_async_clock_acceptance as baseline


class OwnerToolsTests(unittest.TestCase):
    def test_new_pinned_artifacts_and_old_hashes_are_distinct(self):
        for slot in "AB":
            self.assertEqual(deploy.image_info(deploy.pinned_image(slot)[1])[0], slot)
            self.assertNotEqual(deploy.PINNED[slot], old.PINNED[slot])
            self.assertEqual(len(deploy.KNOWN[slot]), 4)
            self.assertEqual(old.image_info(old.pinned_image(slot)[1])[0], slot)

    def test_current_old_a_and_new_b_known_but_pending_or_corrupt_refused(self):
        a = old.pinned_image("A")[1]
        b = deploy.pinned_image("B")[1]
        data = bytearray(b"\xff" * 0x80000)
        data[0x8000:0x8000 + len(a)] = a
        data[0x40000:0x40000 + len(b)] = b
        meta = (0, 0, 1, 0, 0, 381, len(a), zlib.crc32(a), len(b), zlib.crc32(b))
        with patch.object(baseline, "latest_meta", return_value=meta):
            self.assertEqual(deploy.diagnostic_baseline(data)["current"], "A")
            data[0x40010] ^= 1
            with self.assertRaises(RuntimeError):
                deploy.diagnostic_baseline(data)
        with patch.object(baseline, "latest_meta", return_value=meta[:3] + (2,) + meta[4:]):
            with self.assertRaises(RuntimeError):
                deploy.diagnostic_baseline(data)

    def test_owner_marker_and_adc_ready_required_even_when_locked(self):
        good = ("1 OK ZERO PROFILE=LOCKED_DIAGNOSTIC ADC_OWNER=1 ADC_READY=1 "
                "LOCK=1 SD=0 MOE=0 CCER=0 CEN=0 FOC=0 MOTOR_READY=0 IF=0 ACTIVE=0")
        self.assertEqual(deploy.require_owner_service(good)["ADC_OWNER"], "1")
        for old_value, new_value in (("ADC_OWNER=1", ""), ("ADC_OWNER=1", "ADC_OWNER=0"),
                                     ("ADC_READY=1", "ADC_READY=0"), ("SD=0", "SD=1")):
            with self.assertRaises(RuntimeError):
                deploy.require_owner_service(good.replace(old_value, new_value))
        with patch.object(old, "require_fresh_parallel", return_value={"zero": {"ADC_OWNER": "1"}}):
            deploy.require_fresh_owner(None)
        with patch.object(old, "require_fresh_parallel", return_value={"zero": {}}):
            with self.assertRaises(RuntimeError):
                deploy.require_fresh_owner(None)

    def test_exact_evidence_required_before_hardware(self):
        good = {"pass": True, "inspect_only": False, "profile": deploy.PROFILE,
                "target_slot": "B", "image_sha256": deploy.PINNED["B"],
                "final_flash": {"all_protected_regions_unchanged": True},
                "motion_commands": False, "sampling_commands": False,
                "force_confirm": False, "direct_metadata_write": False,
                "physical_drive_off_user_confirmed": True,
                "three_phase_service": {"zero": {"ADC_OWNER": "1"}},
                "final_fw": {"CURRENT": "B", "CONFIRMED": "B", "PENDING": "-",
                             "ATTEMPTS": "0", "ACTIVE": "0", "GEN": "383"}}
        self.assertEqual(sample.deployment_identity(good), ("B", "383"))
        for key, value in (("pass", False), ("inspect_only", True), ("profile", "PARALLEL"),
                           ("image_sha256", old.PINNED["B"]), ("force_confirm", True),
                           ("direct_metadata_write", True), ("sampling_commands", True),
                           ("motion_commands", True), ("physical_drive_off_user_confirmed", False)):
            with self.assertRaises(RuntimeError):
                sample.deployment_identity(dict(good, **{key: value}))
        for path, value in (("owner", "0"), ("pending", "B"), ("generation", ""),
                            ("protected", False)):
            changed = copy.deepcopy(good)
            if path == "owner": changed["three_phase_service"]["zero"]["ADC_OWNER"] = value
            if path == "pending": changed["final_fw"]["PENDING"] = value
            if path == "generation": changed["final_fw"]["GEN"] = value
            if path == "protected": changed["final_flash"]["all_protected_regions_unchanged"] = value
            with self.assertRaises(RuntimeError):
                sample.deployment_identity(changed)

    def test_wrappers_select_the_reviewed_no_retry_engines_and_strict_gates(self):
        with patch.object(old, "main") as run:
            deploy.main()
            self.assertIs(run.call_args.kwargs["image_provider"], deploy.pinned_image)
            self.assertIs(run.call_args.kwargs["fresh_checker"], deploy.require_fresh_owner)
            self.assertEqual(run.call_args.kwargs["profile"], deploy.PROFILE)
        with patch.object(sample.parallel, "main") as run:
            sample.main()
            self.assertIs(run.call_args.kwargs["deployment_checker"], sample.deployment_identity)
            self.assertIs(run.call_args.kwargs["service_checker"], deploy.require_owner_service)
        for module in (deploy, sample):
            source = Path(module.__file__).read_text(encoding="utf-8")
            for forbidden in ('"START"', '"CLEAR"', '"-rst"', '"ZERO SAMPLE"'):
                self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
