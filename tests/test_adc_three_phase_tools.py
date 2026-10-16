"""Offline pinned migration and one-shot UART checks; no hardware access."""
import copy
from pathlib import Path
import struct
import sys
import unittest
from unittest.mock import patch
import zlib

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import adc_three_phase_acceptance as deploy
import adc_three_phase_sample as sample


def baseline_fixture(a_path, b_path, confirmed=1, pending=0):
    a, b = a_path.read_bytes(), b_path.read_bytes()
    data = bytearray(b"\xff" * 0x80000)
    data[0x8000:0x8000 + len(a)] = a
    data[0x40000:0x40000 + len(b)] = b
    meta = (0, 0, confirmed, pending, 0, 375, len(a), zlib.crc32(a), len(b), zlib.crc32(b))
    return data, meta


class ThreePhaseToolsTests(unittest.TestCase):
    def test_target_images_pinned_to_the_correct_slot(self):
        for slot in "AB":
            path, image = deploy.pinned_image(slot)
            self.assertEqual(deploy.image_info(image)[0], slot)
            self.assertTrue(path.is_file())

    def test_known_normal_b_only_admitted_as_inactive_replacement(self):
        data, meta = baseline_fixture(
            ROOT / "foc2_app_a/build/AdcDmaRaw20261009/foc2.bin",
            ROOT / "foc2_app_b/build/PoweredSpeedBounded20261009/foc2.bin")
        with patch.object(deploy, "latest_meta", return_value=meta):
            result = deploy.diagnostic_baseline(data)
        self.assertTrue(result["images"]["A"]["output_locked_image"])
        self.assertFalse(result["images"]["B"]["output_locked_image"])
        for changed in (meta[:2] + (2,) + meta[3:], meta[:3] + (2,) + meta[4:]):
            with patch.object(deploy, "latest_meta", return_value=changed):
                with self.assertRaises(RuntimeError): deploy.diagnostic_baseline(data)
        data[0x8010] ^= 1
        with patch.object(deploy, "latest_meta", return_value=meta):
            with self.assertRaises(RuntimeError): deploy.diagnostic_baseline(data)

    def test_both_three_phase_images_admitted_with_either_confirmed(self):
        for confirmed in (1, 2):
            data, meta = baseline_fixture(deploy.pinned_image("A")[0], deploy.pinned_image("B")[0], confirmed)
            with patch.object(deploy, "latest_meta", return_value=meta):
                result = deploy.diagnostic_baseline(data)
            self.assertEqual(result["current"], "A" if confirmed == 1 else "B")
            self.assertTrue(all(x["output_locked_image"] for x in result["images"].values()))

    def test_unknown_inactive_image_or_crc_rejected(self):
        data, meta = baseline_fixture(deploy.pinned_image("A")[0], deploy.pinned_image("B")[0])
        data[0x40010] ^= 1
        b = bytes(data[0x40000:0x40000 + meta[8]])
        meta = meta[:9] + (zlib.crc32(b),)
        with patch.object(deploy, "latest_meta", return_value=meta):
            with self.assertRaises(RuntimeError): deploy.diagnostic_baseline(data)

    def test_sample_never_resent_after_lost_ack(self):
        class Port:
            def __init__(self): self.writes = []
            def write(self, data): self.writes.append(data)
        port = Port()
        uart = deploy.ThreePhaseUart(port)
        with self.assertRaises(TimeoutError): uart.raw_query("ADC 3PH SAMPLE", timeout=0)
        with self.assertRaises(RuntimeError): uart.raw_query("ADC 3PH SAMPLE", timeout=0)
        self.assertEqual(len(port.writes), 1)
        self.assertEqual(uart.sample_commands, 1)
        for command in ("ZERO SAMPLE", "START", "ADC DMA SAMPLE", "ADC 3PH RESET"):
            with self.assertRaises(ValueError): uart.raw_query(command, timeout=0)

    def test_deployment_evidence_must_prove_pin_protection_and_confirmation(self):
        good = {"pass": True, "inspect_only": False, "target_slot": "B",
                "image_sha256": deploy.PINNED["B"],
                "final_flash": {"all_protected_regions_unchanged": True},
                "motion_commands": False, "sampling_commands": False,
                "final_fw": {"CURRENT": "B", "CONFIRMED": "B", "PENDING": "-",
                             "ATTEMPTS": "0", "ACTIVE": "0", "GEN": "377"}}
        self.assertEqual(sample.deployment_identity(good), ("B", "377"))
        for key, value in (("pass", False), ("inspect_only", True),
                           ("image_sha256", deploy.OLD_NORMAL_B), ("sampling_commands", True)):
            changed = dict(good, **{key: value})
            with self.assertRaises(RuntimeError): sample.deployment_identity(changed)
        changed = copy.deepcopy(good)
        changed["final_fw"]["PENDING"] = "B"
        with self.assertRaises(RuntimeError): sample.deployment_identity(changed)

    def test_sample_host_cannot_flash_reset_clear_or_move(self):
        source = Path(sample.__file__).read_text(encoding="utf-8")
        for bad in ('"FW END"', '"FW CONFIRM"', '"-rst"', '"START"', '"CLEAR"', '"ZERO SAMPLE"'):
            self.assertNotIn(bad, source)
        self.assertIn("require_supply", source)
        self.assertIn("require_registers", source)
        self.assertIn("verify_capture", source)


if __name__ == "__main__":
    unittest.main()
