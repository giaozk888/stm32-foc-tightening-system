"""Offline actual-C tests only; no serial, SWD, reset or Flash access."""
import ctypes
from pathlib import Path
import random
import struct
import subprocess
import sys
import unittest
from unittest.mock import patch
import zlib

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import adc_reference_double_report as report
from tests.test_adc_parallel import Summary
from tests.test_adc_reference_input import FLAGS
from tests.test_adc_reference_tools import status
import adc_reference_double_acceptance as deploy
import adc_reference_double_sample as sample
import adc_reference_double_readback as readback
import zero_async_clock_acceptance as baseline

GCC = r"D:\Qt\Tools\mingw1310_64\bin\gcc.exe"


class DoubleCaptureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = ROOT / "tests/adc_reference_double_build"
        cls.directory.mkdir(exist_ok=True)
        cls.common = [GCC, "-std=c11", "-O2", "-Wall", "-Wextra", "-Werror", "-pedantic", "-UNDEBUG"]

    def test_actual_adapter_all_cleanup_scenarios(self):
        exe = self.directory / "adapter.exe"
        subprocess.run(self.common + ["-DADC_CONTROL_PINS_LOW_DIAGNOSTIC=1",
            "-DADC_DMA_REFERENCE_INPUT_DIAGNOSTIC=1", "-DADC_DMA_REFERENCE_DOUBLE_CAPTURE=1",
            "-I" + str(ROOT / "tests/adc_dma_mock"), "-I" + str(ROOT / "firmware_common"),
            str(ROOT / "tests/adc12_adapter_host.c"), str(ROOT / "firmware_common/adc_raw_report.c"),
            "-o", str(exe)], check=True)
        for scenario in list(range(21)) + list(range(101, 111)) + list(range(211, 219)):
            with self.subTest(scenario=scenario):
                subprocess.run([str(exe), str(scenario)], capture_output=True, check=True)

    def test_actual_console_and_last_block(self):
        exe = self.directory / "console.exe"
        subprocess.run(self.common + ["-DZERO_RETEST_BOOT=1", "-DADC_DMA_RAW_DIAGNOSTIC=1",
            "-DADC_CONTROL_PINS_LOW_DIAGNOSTIC=1", "-DADC_DMA_REFERENCE_DOUBLE_CAPTURE=1",
            "-I" + str(ROOT / "tests/adc_dma_mock"), str(ROOT / "tests/adc_reference_console_host.c"),
            "-o", str(exe)], check=True)
        for scenario in range(10):
            subprocess.run([str(exe), str(scenario)], capture_output=True, check=True)

    def test_incomplete_profile_cannot_compile(self):
        flags = FLAGS + ["ADC_CONTROL_PINS_LOW_DIAGNOSTIC", "ADC_DMA_REFERENCE_DOUBLE_CAPTURE"]
        for missing in flags[:-1]:
            source = '#include "adc_dma_diag.h"\n'
            result = subprocess.run(self.common + ["-fsyntax-only", "-x", "c", "-",
                *["-D" + f for f in flags if f != missing],
                "-I" + str(ROOT / "firmware_common"), "-I" + str(ROOT / "tests/adc_dma_mock")],
                input=source, text=True, capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("Double capture requires", result.stderr)

    def test_virtual_w_crc_retains_last_pair_and_rejects_bad_raw(self):
        dll = self.directory / "report.dll"
        subprocess.run(self.common + ["-shared", str(ROOT / "firmware_common/adc_raw_report.c"),
                                      "-o", str(dll)], check=True)
        lib = ctypes.CDLL(str(dll))
        fn = lib.AdcRaw_SummarizeUvPadding
        fn.argtypes = [ctypes.POINTER(ctypes.c_uint16)] * 2 + [ctypes.c_size_t, ctypes.POINTER(Summary)]
        fn.restype = ctypes.c_int
        rng = random.Random(1118192)
        for n in (1, 8, 4096, 8192):
            pairs = [(rng.randrange(4096), rng.randrange(4096)) for _ in range(n)]
            u = (ctypes.c_uint16*n)(*(p[0] for p in pairs))
            v = (ctypes.c_uint16*n)(*(p[1] for p in pairs))
            summary = Summary()
            self.assertEqual(fn(u, v, n, ctypes.byref(summary)), 1)
            self.assertEqual(summary.crc32, zlib.crc32(b"".join(struct.pack("<HHH", a, b, 0) for a, b in pairs)))
            self.assertEqual((summary.min_w, summary.max_w), (0, 0))
            u[n-1] = 4096
            self.assertEqual(fn(u, v, n, ctypes.byref(summary)), 0)
        self.assertEqual(fn(None, v, 8192, ctypes.byref(summary)), 0)
        self.assertEqual(fn(v, v, 0, ctypes.byref(summary)), 0)

    def test_offline_extended_identity_and_integrity(self):
        triples = [(0, 0, 0)] * 8192
        crc = zlib.crc32(bytes(8192*6))
        line = (status("ON", 12000).replace("4096", "8192").replace("MS=205", "MS=410")
                .replace("RANGE=1000:1000,2048:2048,0:0", "RANGE=0:0,0:0,0:0"))
        import re
        line = re.sub(r"CRC=[0-9A-F]{8}", f"CRC={crc:08X}", line)
        line = re.sub(r"\bMS=\d+", "MS=410", line)
        if "MS=" not in line:
            line += " MS=410"
        line = re.sub(r"\bRANGE=\S+", "RANGE=0:0,0:0,0:0", line)
        line += " PIN_POLICY=GPIO_LOW PIN_CFG=1 PIN_LEVEL=1 WINDOW=DOUBLE RAW_STORAGE=UV_ONLY"
        self.assertEqual(report.verify_capture(line, triples, power="ON"), f"{crc:08X}")
        for bad in (triples[:-1], [(0, 0, 1)] + triples[1:], triples[:-1] + [(1, 0, 0)]):
            with self.assertRaises(ValueError): report.verify_capture(line, bad, power="ON")
        for bad in (line.replace("CAP=8192", "CAP=4096"), line.replace("WINDOW=DOUBLE", "WINDOW=SINGLE"),
                    line.replace("NU=8192", "NU=8191"), line.replace("MS=410", "MS=205"),
                    line.replace("PIN_CFG=1", "PIN_CFG=0")):
            with self.assertRaises(ValueError): report.require_status(bad, terminal=True, power="ON")
        block = "2 OK ADC3PAR_DATA I=8184 N=8 UVW=" + "000000000000"*8
        self.assertEqual(report.decode_block(block, 8184), [(0, 0, 0)]*8)
        with self.assertRaises(ValueError): report.decode_block(block.replace("8184", "8192"), 8192)

    def test_new_option_default_off_both_slots(self):
        for app in ("foc2_app_a", "foc2_app_b"):
            cmake = (ROOT/app/"CMakeLists.txt").read_text(encoding="utf-8")
            self.assertIn('option(ADC_DMA_REFERENCE_DOUBLE_CAPTURE "Locked GPIO-low ADC1/2 ONLY: 8192 pairs at unchanged 20 kHz" OFF)', cmake)
            self.assertIn("ADC_DMA_REFERENCE_DOUBLE_CAPTURE AND NOT ADC_CONTROL_PINS_LOW_DIAGNOSTIC", cmake)

    def test_pinned_binary_and_only_confirmed_a_deploy_baseline(self):
        import adc_reference_acceptance as original
        a = deploy.pinned_image("A")[1]
        b = original.pinned_image("B")[1]
        self.assertEqual(deploy.image_info(deploy.pinned_image("B")[1])[0], "B")
        data = bytearray(b"\xff"*0x80000)
        data[0x8000:0x8000+len(a)] = a
        data[0x40000:0x40000+len(b)] = b
        meta = (0, 0, 1, 0, 0, 399, len(a), zlib.crc32(a), len(b), zlib.crc32(b))
        with patch.object(baseline, "latest_meta", return_value=meta):
            self.assertEqual(deploy.diagnostic_baseline(data)["current"], "A")
            data[0x8010] ^= 1
            with self.assertRaises(RuntimeError): deploy.diagnostic_baseline(data)
        with patch.object(baseline, "latest_meta", return_value=meta[:2]+(2,)+meta[3:]):
            with self.assertRaises(RuntimeError): deploy.diagnostic_baseline(data)

    def test_gpio_validator_includes_b_vtor_and_all_output_pins(self):
        regs = {a: 0 for a in deploy.fallback.PIN_ADDRESSES}
        regs.update({0x48000400: 0x04000005, 0x48000800: 0x15, 0xE000ED08: 0x08040000})
        def text(values): return "\n".join(f"0x{a:08X} : {v:08X}" for a,v in values.items())
        deploy.require_pin_registers(text(regs))
        for address, bit in ((0xE000ED08, 18), (0x48000410, 1), (0x48000814, 6),
                             (0x40012C00, 0), (0x40012C44, 15)):
            bad = dict(regs); bad[address] ^= 1 << bit
            with self.assertRaises(RuntimeError): deploy.require_pin_registers(text(bad))

    def test_live_wrappers_remain_one_shot_and_use_full_extended_data(self):
        with patch.object(sys, "argv", ["sample", "--both-ground-confirmed", "--all-six-connected"]), \
             patch.object(sample.parallel, "main") as run:
            sample.main()
        args = run.call_args.kwargs
        self.assertEqual(args["capacity"], 8192)
        self.assertIs(args["block_decoder"], report.decode_block)
        self.assertEqual(args["quiet_wait_seconds"], 1.)
        self.assertEqual(args["sample_command"], "ADC PAR SAMPLE ON")
        self.assertIs(args["uart_factory"], sample.ReferenceUart)
        with patch.object(readback.shared, "main") as run:
            readback.main()
        self.assertEqual(run.call_args.kwargs["stored_channels"], 2)
        self.assertEqual(run.call_args.kwargs["capacity"], 8192)
        self.assertEqual(run.call_args.kwargs["expected_slot"], "B")

    def test_old_capture_rejected_before_probe_by_extended_readback(self):
        with patch.object(sys, "argv", ["readback", "--capture", "unused.json"]), \
             patch.object(Path, "read_text", return_value='{}'), \
             patch.object(readback.shared.subprocess, "run") as cli:
            with self.assertRaises(RuntimeError): readback.main()
            cli.assert_not_called()


if __name__ == "__main__": unittest.main()
