"""Offline GPIO/HAL model; never connects to a board."""
from pathlib import Path
import subprocess
import sys
import unittest
import zlib
import struct
import copy
import json
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
GCC = r"D:\Qt\Tools\mingw1310_64\bin\gcc.exe"
FLAGS = ["ADC_CONTROL_PINS_LOW_DIAGNOSTIC", "ZERO_RETEST_BOOT", "ADC_DMA_REFERENCE_INPUT_DIAGNOSTIC"]
sys.path.insert(0, str(ROOT / "tools"))
import adc_control_pins_low_acceptance as deploy
import adc_control_pins_low_sample as sample
import zero_async_clock_acceptance as baseline
from tests.test_adc_reference_tools import status

class ActiveLowTests(unittest.TestCase):
    def test_actual_extended_status_formatter(self):
        directory = ROOT / "tests/adc_control_pins_low_build"
        directory.mkdir(exist_ok=True)
        target = directory / "console.exe"
        subprocess.run([GCC, "-std=c11", "-O2", "-Wall", "-Wextra", "-Werror", "-UNDEBUG",
                        "-DADC_CONTROL_PINS_LOW_DIAGNOSTIC", "-I" + str(ROOT / "tests/adc_dma_mock"),
                        str(ROOT / "tests/adc_reference_console_host.c"), "-o", str(target)], check=True)
        for scenario in range(8):
            subprocess.run([str(target), str(scenario)], check=True, capture_output=True, text=True)

    def test_profile_and_actual_pinned_artifacts(self):
        self.assertEqual(deploy.image_info(deploy.pinned_image("A")[1])[0], "A")
        self.assertEqual(deploy.image_info(deploy.pinned_image("B")[1])[0], "B")
        good = status("ON", 12000) + " PIN_POLICY=GPIO_LOW PIN_CFG=1 PIN_LEVEL=1"
        deploy.require_status(good, terminal=True, power="ON")
        for bad in (status("ON", 12000), good.replace("PIN_CFG=1", "PIN_CFG=0"),
                    good.replace("PIN_LEVEL=1", "PIN_LEVEL=0"), good.replace("GPIO_LOW", "AF")):
            with self.assertRaises(ValueError): deploy.require_status(bad, terminal=True, power="ON")

    def test_only_exact_confirmed_b_can_stage_a(self):
        a = deploy.reference_image("A")[1]; b = deploy.reference_image("B")[1]
        data = bytearray(b"\xff" * 0x80000)
        data[0x8000:0x8000 + len(a)] = a; data[0x40000:0x40000 + len(b)] = b
        meta = (0, 0, 2, 0, 0, 396, len(a), zlib.crc32(a), len(b), zlib.crc32(b))
        with patch.object(baseline, "latest_meta", return_value=meta):
            self.assertEqual(deploy.diagnostic_baseline(data)["current"], "B")
            data[0x40010] ^= 1
            with self.assertRaises(RuntimeError): deploy.diagnostic_baseline(data)
            data[0x40010] ^= 1; data[0x8010] ^= 1
            with self.assertRaises(RuntimeError): deploy.diagnostic_baseline(data)
            data[0x8010] ^= 1
        for changed in (meta[:2] + (1,) + meta[3:], meta[:3] + (1,) + meta[4:]):
            with patch.object(baseline, "latest_meta", return_value=changed):
                with self.assertRaises(RuntimeError): deploy.diagnostic_baseline(data)

    def test_register_validation_checks_every_pin_and_lock(self):
        regs = {a: 0 for a in deploy.PIN_ADDRESSES}
        regs.update({0x48000400: 0x04000005, 0x48000800: 0x15, 0xE000ED08: 0x08008000})
        def output(values):
            return "\n".join(f"0x{a:08X} : {v:08X}" for a, v in values.items())
        deploy.require_pin_registers(output(regs))
        for base, pins in ((0x48000400, (0, 1, 13)), (0x48000800, (0, 1, 2))):
            for pin in pins:
                for off, bit in ((0, 2 * pin), (4, pin), (8, 2 * pin), (12, 2 * pin), (16, pin), (20, pin)):
                    bad = dict(regs); bad[base + off] ^= 1 << bit
                    with self.assertRaises(RuntimeError): deploy.require_pin_registers(output(bad))
        for address, bit in ((0x40012C00, 0), (0x40012C20, 0), (0x40012C44, 14),
                             (0x40012C44, 15), (0x48000814, 6), (0xE000ED08, 18)):
            bad = dict(regs); bad[address] ^= 1 << bit
            with self.assertRaises(RuntimeError): deploy.require_pin_registers(output(bad))
        bad = dict(regs); bad.pop(0x48000410)
        with self.assertRaises(RuntimeError): deploy.require_pin_registers(output(bad))

    def test_sampling_identity_rejects_old_profile_and_non_low_pins(self):
        old = json.loads((ROOT / "safety_backups/adc-reference-input-live-20261010/deployment-1791639370434693100.json").read_text(encoding="utf-8"))
        with self.assertRaises(RuntimeError): sample.deployment_identity(old)
        good = copy.deepcopy(old)
        good.update(profile=deploy.PROFILE, target_slot="A", image_sha256=deploy.PINNED["A"])
        good["final_fw"].update(CURRENT="A", CONFIRMED="A")
        good["three_phase_service"]["raw"].update(PIN_POLICY="GPIO_LOW", PIN_CFG="1", PIN_LEVEL="1")
        self.assertEqual(sample.deployment_identity(good)[0], "A")
        for key in ("PIN_POLICY", "PIN_CFG", "PIN_LEVEL"):
            bad = copy.deepcopy(good); bad["three_phase_service"]["raw"].pop(key)
            with self.assertRaises(RuntimeError): sample.deployment_identity(bad)

    def test_single_ground_sample_wrapper_keeps_supply_and_no_retry(self):
        for state in ("on", "off"):
            argv = ["sample", "--power-" + state, "--both-ground-confirmed", "--pa0-measured-volts", "0", "--pa1-measured-volts", "0"]
            with patch.object(sys, "argv", argv), patch.object(sample.parallel, "main") as run:
                sample.main()
            call = run.call_args.kwargs
            self.assertEqual(call["sample_command"], "ADC PAR SAMPLE " + state.upper())
            self.assertIs(call["fresh_checker"], deploy.require_fresh_low)
            self.assertTrue(call["quiet_acquisition"])
            self.assertEqual(call["supply_checker"].keywords, {"power": state.upper()})
            self.assertIn("MCU GND", call["raw_mapping"]["U"])
            self.assertIn("UNSAMPLED", call["raw_mapping"]["W"])

    def test_actual_helper_against_register_model(self):
        directory = ROOT / "tests/adc_control_pins_low_build"
        directory.mkdir(exist_ok=True)
        target = directory / "pins.exe"
        subprocess.run([GCC, "-std=c11", "-O2", "-Wall", "-Wextra", "-Werror", "-pedantic",
                        "-UNDEBUG", *["-D" + f for f in FLAGS],
                        str(ROOT / "tests/adc_control_pins_low_host.c"), "-o", str(target)], check=True)
        subprocess.run([str(target)], check=True)

    def test_incomplete_profile_rejected(self):
        for missing in FLAGS:
            p = subprocess.run([GCC, "-std=c11", "-fsyntax-only",
                                *["-D" + f for f in FLAGS if f != missing],
                                str(ROOT / "tests/adc_control_pins_low_host.c")], capture_output=True, text=True)
            self.assertNotEqual(p.returncode, 0)
            self.assertIn("Active-low pins require", p.stderr)

    def test_default_off_and_startup_order_both_slots(self):
        for slot in "ab":
            source = (ROOT / f"foc2_app_{slot}/Core/Src/main.c").read_text(encoding="utf-8")
            init = source[source.index("  MX_GPIO_Init();"):]
            self.assertLess(init.index("MX_TIM1_Init();"), init.index("AdcControlPins_InitLow();"))
            self.assertLess(init.index("AdcControlPins_InitLow();"), init.index("MX_ADC1_Init();"))
            cmake = (ROOT / f"foc2_app_{slot}/CMakeLists.txt").read_text(encoding="utf-8")
            self.assertIn('option(ADC_CONTROL_PINS_LOW_DIAGNOSTIC "Locked reference ONLY: six control pins held GPIO low" OFF)', cmake)
            self.assertIn("ADC_CONTROL_PINS_LOW_DIAGNOSTIC AND NOT ADC_DMA_REFERENCE_INPUT_DIAGNOSTIC", cmake)
        boot = (ROOT / "firmware_common/zero_retest_boot.inc").read_text(encoding="utf-8")
        self.assertIn("if (!AdcControlPins_ConfigLow() || !AdcControlPins_LevelLow()) return 0U;", boot)
        console = (ROOT / "firmware_common/adc_parallel_console.inc").read_text(encoding="utf-8")
        self.assertIn("PIN_POLICY=GPIO_LOW PIN_CFG=%u PIN_LEVEL=%u", console)

if __name__ == "__main__": unittest.main()
