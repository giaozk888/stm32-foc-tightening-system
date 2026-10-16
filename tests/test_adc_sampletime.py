"""Offline-only real adapter and exact deployment gates for the sampling contrast."""
import copy
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch
import zlib

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import adc_sampletime_acceptance as deploy
import adc_sampletime_sample as sample
import adc_owner_acceptance as owner
import adc_parallel_acceptance as parallel
import zero_async_clock_acceptance as baseline
from tests.test_adc_parallel import status


class SampleTimeTests(unittest.TestCase):
    def test_actual_long_adapter_and_all_sampling_readback_failures(self):
        directory = ROOT / "tests/adc_parallel_build"
        directory.mkdir(exist_ok=True)
        exe = directory / "adapter_long.exe"
        subprocess.run([
            r"D:\Qt\Tools\mingw1310_64\bin\gcc.exe", "-std=c11", "-O2", "-Wall", "-Wextra",
            "-Werror", "-pedantic", "-UNDEBUG", "-DADC_DMA_PARALLEL_LONG_SAMPLE=1",
            "-I", str(ROOT / "tests/adc_dma_mock"), "-I", str(ROOT / "firmware_common"),
            str(ROOT / "tests/adc_parallel_adapter_host.c"),
            str(ROOT / "firmware_common/adc_raw_report.c"), "-o", str(exe)], check=True)
        cases = (list(range(19)) + list(range(20, 23)) + list(range(30, 36)) +
                 list(range(40, 43)) + list(range(101, 115)) + list(range(215, 222)))
        for case in cases:
            with self.subTest(case=case):
                subprocess.run([str(exe), str(case)], check=True, capture_output=True, text=True)

    def test_exact_artifact_and_b_fallback_only(self):
        a = deploy.pinned_image("A")[1]
        b = owner.pinned_image("B")[1]
        self.assertEqual(deploy.image_info(a)[0], "A")
        self.assertEqual(deploy.pinned_image("B")[1], b)
        old_a = parallel.pinned_image("A")[1]
        data = bytearray(b"\xff" * 0x80000)
        data[0x8000:0x8000 + len(old_a)] = old_a
        data[0x40000:0x40000 + len(b)] = b
        meta = (0, 0, 2, 0, 0, 384, len(old_a), zlib.crc32(old_a), len(b), zlib.crc32(b))
        with patch.object(baseline, "latest_meta", return_value=meta):
            self.assertEqual(deploy.diagnostic_baseline(data)["current"], "B")
            data[0x40010] ^= 1
            with self.assertRaises(RuntimeError):
                deploy.diagnostic_baseline(data)
            data[0x40010] ^= 1
        with patch.object(baseline, "latest_meta", return_value=meta[:2] + (1,) + meta[3:]):
            with self.assertRaises(RuntimeError):
                deploy.diagnostic_baseline(data)

    def test_long_marker_and_smpr_mask_required(self):
        good = status() + " SMP_CYCLES=247.5 SMP_CHECK=7"
        deploy.require_long_status(good, terminal=True)
        for change in (good.replace("247.5", "12.5"), good.replace("SMP_CHECK=7", "SMP_CHECK=3"),
                       status(), good.replace("SD=0", "SD=1")):
            with self.assertRaises((RuntimeError, ValueError)):
                deploy.require_long_status(change, terminal=True)
        fresh = {"raw": {"SMP_CYCLES": "247.5", "SMP_CHECK": "0"}}
        with patch.object(owner, "require_fresh_owner", return_value=fresh):
            self.assertIs(deploy.require_fresh_long(None), fresh)
        for field, value in (("SMP_CYCLES", "12.5"), ("SMP_CHECK", "7")):
            bad = copy.deepcopy(fresh)
            bad["raw"][field] = value
            with patch.object(owner, "require_fresh_owner", return_value=bad):
                with self.assertRaises(RuntimeError):
                    deploy.require_fresh_long(None)

    def test_exact_deployment_before_hardware_and_wrapper_selection(self):
        good = {"pass": True, "inspect_only": False, "profile": deploy.PROFILE,
                "target_slot": "A", "image_sha256": deploy.PINNED["A"],
                "final_flash": {"all_protected_regions_unchanged": True},
                "motion_commands": False, "sampling_commands": False,
                "force_confirm": False, "direct_metadata_write": False,
                "physical_drive_off_user_confirmed": True,
                "three_phase_service": {"zero": {"ADC_OWNER": "1"},
                    "raw": {"SMP_CYCLES": "247.5", "SMP_CHECK": "0"}},
                "final_fw": {"CURRENT": "A", "CONFIRMED": "A", "PENDING": "-",
                             "ATTEMPTS": "0", "ACTIVE": "0", "GEN": "387"}}
        self.assertEqual(sample.deployment_identity(good), ("A", "387"))
        for key, value in (("pass", False), ("profile", owner.PROFILE),
                           ("image_sha256", owner.PINNED["A"]), ("force_confirm", True),
                           ("physical_drive_off_user_confirmed", False)):
            with self.assertRaises(RuntimeError):
                sample.deployment_identity(dict(good, **{key: value}))
        bad = copy.deepcopy(good)
        bad["three_phase_service"]["raw"]["SMP_CHECK"] = "7"
        with self.assertRaises(RuntimeError):
            sample.deployment_identity(bad)
        with patch.object(parallel, "main") as run:
            deploy.main()
            self.assertIs(run.call_args.kwargs["baseline_checker"], deploy.diagnostic_baseline)
        with patch.object(sample.parallel, "main") as run:
            sample.main()
            self.assertIs(run.call_args.kwargs["status_checker"], deploy.require_long_status)

    def test_diagnostic_option_only_and_default_unchanged(self):
        for slot in "ab":
            text = (ROOT / f"foc2_app_{slot}/CMakeLists.txt").read_text(encoding="utf-8")
            self.assertIn('option(ADC_DMA_PARALLEL_LONG_SAMPLE "Locked diagnostic-only 247.5-cycle sampling contrast" OFF)', text)
            self.assertIn("ADC_DMA_PARALLEL_LONG_SAMPLE AND NOT ADC_DMA_PARALLEL_DIAGNOSTIC", text)
        for module in (deploy, sample):
            source = Path(module.__file__).read_text(encoding="utf-8")
            for forbidden in ('"START"', '"CLEAR"', '"-rst"', '"ZERO SAMPLE"'):
                self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
