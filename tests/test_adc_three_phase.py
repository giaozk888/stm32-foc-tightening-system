"""Actual C adapter/CRC under a HAL model and offline transcript contracts.
No electrical, timing, powered control, UART or SWD validation.
"""
import ctypes
from pathlib import Path
import random
import struct
import subprocess
import sys
import unittest
import zlib

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import adc_three_phase_report as report

GCC = r"D:\Qt\Tools\mingw1310_64\bin\gcc.exe"


class ThreeReport(ctypes.Structure):
    _fields_ = [(n, ctypes.c_uint16) for n in ("min_u", "max_u", "min_v", "max_v", "min_w", "max_w")] + [
        ("crc32", ctypes.c_uint32)]


def status(crc):
    return ("1 OK ADC3PH CH=3 REAL_W=1 W_DELAY=SEQ LOCK=1 SD=0 MOE=0 CCER=0 "
            "CEN=0 FOC=0 STATE=4 REASON=0 NU=4096 NV=4096 NW=4096 IRQ=1,1 "
            f"ERR=0,0 RESTORE=1 CRC={crc:08X} CAP=4096")


def transcript(triples):
    crc = zlib.crc32(b"".join(struct.pack("<HHH", *t) for t in triples))
    lines = [status(crc)]
    for first in range(0, 4096, 8):
        payload = "".join(f"{u:04X}{v:04X}{w:04X}" for u, v, w in triples[first:first+8])
        lines.append(f"2 OK ADC3PH_DATA I={first} N=8 UVW={payload}")
    return lines


class ThreePhaseCTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = ROOT / "tests/adc_three_phase_build"
        cls.directory.mkdir(exist_ok=True)
        path = cls.directory / "adc_three_report.dll"
        subprocess.run([GCC, "-std=c11", "-O2", "-Wall", "-Wextra", "-Werror", "-pedantic", "-shared",
                        str(ROOT / "firmware_common/adc_raw_report.c"), "-o", str(path)], check=True)
        cls.library = ctypes.CDLL(str(path))
        cls.summarize = cls.library.AdcRaw_SummarizeThreePhase
        cls.summarize.argtypes = [ctypes.POINTER(ctypes.c_uint16), ctypes.POINTER(ctypes.c_uint16),
                                 ctypes.c_size_t, ctypes.POINTER(ThreeReport)]
        cls.summarize.restype = ctypes.c_int
        cls.executable = cls.directory / "adc_three_adapter.exe"
        subprocess.run([GCC, "-std=c11", "-O2", "-Wall", "-Wextra", "-Werror", "-pedantic", "-UNDEBUG",
                        "-DADC_DMA_THREE_PHASE_DIAGNOSTIC=1",
                        "-I", str(ROOT / "tests/adc_dma_mock"), "-I", str(ROOT / "firmware_common"),
                        str(ROOT / "tests/adc_dma_adapter_host.c"),
                        str(ROOT / "firmware_common/adc_raw_report.c"), "-o", str(cls.executable)], check=True)

    def test_actual_adapter_setup_errors_cleanup_and_capture_order(self):
        for scenario in list(range(16)) + list(range(101, 112)) + list(range(212, 218)):
            with self.subTest(scenario=scenario):
                subprocess.run([str(self.executable), str(scenario)], check=True, capture_output=True, text=True)

    def test_logical_crc_differs_from_dma_layout_and_matches_python(self):
        rng = random.Random(301010)
        for count in (1, 8, 4096):
            triples = [tuple(rng.randrange(4096) for _ in range(3)) for _ in range(count)]
            uw = (ctypes.c_uint16 * (count*2))(*(v for u, _, w in triples for v in (u, w)))
            vv = (ctypes.c_uint16 * count)(*(v for _, v, _ in triples))
            result = ThreeReport()
            self.assertEqual(self.summarize(uw, vv, count, ctypes.byref(result)), 1)
            self.assertEqual(result.crc32, zlib.crc32(b"".join(struct.pack("<HHH", *t) for t in triples)))
            expected = tuple(value for phase in range(3) for value in
                             (min(t[phase] for t in triples), max(t[phase] for t in triples)))
            self.assertEqual(tuple(getattr(result, n) for n, _ in ThreeReport._fields_[:-1]), expected)

    def test_invalid_w_does_not_publish_partial_summary(self):
        result = ThreeReport(11, 22, 33, 44, 55, 66, 77)
        uw = (ctypes.c_uint16 * 2)(1558, 4096)
        v = (ctypes.c_uint16 * 1)(1558)
        self.assertEqual(self.summarize(uw, v, 1, ctypes.byref(result)), 0)
        self.assertEqual((result.min_w, result.crc32), (55, 77))
        self.assertEqual(self.summarize(None, v, 1, ctypes.byref(result)), 0)


class ThreePhaseExportTests(unittest.TestCase):
    def test_full_transcript_and_crc(self):
        triples = [(1558 + i % 7, 1550 + i % 9, 1560 + i % 13) for i in range(4096)]
        _, decoded, _ = report.read_transcript("\n".join(transcript(triples)))
        self.assertEqual(decoded, triples)

    def test_missing_duplicate_mixed_or_corrupted_blocks_rejected(self):
        lines = transcript([(1558, 1557, 1556)] * 4096)
        for altered in (lines[:-1], lines + [lines[1]], lines + [lines[0].replace("CRC=", "CRC=FF")],
                        [lines[0]] + [lines[1].replace("0616", "0617", 1)] + lines[2:]):
            with self.assertRaises(ValueError):
                report.read_transcript("\n".join(altered))

    def test_incomplete_unlocked_or_legacy_status_refused(self):
        good = status(0)
        report.require_status(good, terminal=True)
        for old, new in (("REAL_W=1", "REAL_W=0"), ("LOCK=1", "LOCK=0"), ("SD=0", "SD=1"),
                         ("MOE=0", "MOE=1"), ("CCER=0", "CCER=1"), ("FOC=0", "FOC=1"),
                         ("CEN=0", "CEN=1"), ("NW=4096", "NW=4095"), ("IRQ=1,1", "IRQ=2,1"),
                         ("ERR=0,0", "ERR=1,0"), ("RESTORE=1", "RESTORE=0"), ("ADC3PH", "ADC_DMA")):
            with self.assertRaises(ValueError):
                report.require_status(good.replace(old, new), terminal=True)

    def test_block_width_range_and_order(self):
        line = "2 OK ADC3PH_DATA I=0 N=8 UVW=" + "061606150614"*8
        self.assertEqual(report.decode_block(line, 0), [(1558, 1557, 1556)]*8)
        for bad in (line[:-1], line.replace("I=0", "I=8"), line.replace("N=8", "N=16"),
                    line.replace("0614", "FFFF", 1)):
            with self.assertRaises(ValueError):
                report.decode_block(bad, 0)

    def test_abnormal_w_is_kept_and_residual_is_not_forced_zero(self):
        data = [(1558, 1558, 1558), (1558, 1558, 1900), (1558, 1558, 0)]
        result = report.analyze(data, [1558, 1558, 1558])
        self.assertEqual(result["W"]["min"], 0)
        self.assertEqual(result["W"]["max"], 1900)
        self.assertEqual(result["sum_residual_counts"]["max_abs"], 1558)
        self.assertFalse(result["signal_quality_qualified"])
        self.assertFalse(result["motor_qualified"])

    def test_feature_is_opt_in_non_actuating_and_does_not_replace_foc_w(self):
        for slot in "ab":
            cmake = (ROOT / f"foc2_app_{slot}/CMakeLists.txt").read_text(encoding="utf-8")
            self.assertIn('option(ADC_DMA_THREE_PHASE_DIAGNOSTIC', cmake)
            self.assertIn('ADC_DMA_THREE_PHASE_DIAGNOSTIC AND NOT ADC_DMA_RAW_DIAGNOSTIC', cmake)
            main = (ROOT / f"foc2_app_{slot}/Core/Src/main.c").read_text(encoding="utf-8")
            self.assertIn("iw_A = -(iu_A + iv_A);", main)
        console = (ROOT / "firmware_common/adc_three_phase_console.inc").read_text(encoding="utf-8")
        for key in ('"ADC 3PH SAMPLE"',
                    'ZeroRetest_SubmitAcquisition(request_id, ZERO_ADC_ACQUIRE_DMA);',
                    'ADC3PH_USE_THREE_CHANNEL_COMMANDS', 'ADC3PH_SAMPLING_ACTIVE'):
            self.assertIn(key, console)
        owner = (ROOT / "firmware_common/zero_adc_owner.inc").read_text(encoding="utf-8")
        for key in ('BootHealth_IsCurrentTrial() || fw_update.active',
                    'bus_mv < 10000U || bus_mv > 14000U',
                    '!ZeroRetest_Locked()', 'ZERO_ADC_DMA_PREFIX "ADC3PH"'):
            self.assertIn(key, owner)
        for bad in ('ADC_AnalogLiveSample(', 'AdcDmaDiag_Start('):
            self.assertNotIn(bad, console)
        for bad in ('PowerStage_Enable(', 'FOC_CurrentLoopStep(', 'iu_zero_raw =', 'iw_zero_raw ='):
            self.assertNotIn(bad, console + owner)
        locked = (ROOT / "firmware_common/zero_retest_boot.inc").read_text(encoding="utf-8")
        self.assertIn('ADC3PH_RAW_ONLY_NO_ZERO_PUBLICATION', locked)


if __name__ == "__main__":
    unittest.main()
