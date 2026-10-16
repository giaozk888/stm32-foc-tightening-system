"""Offline guards for the isolated board observer; never opens a serial port."""
import sys
from pathlib import Path
import unittest
from dataclasses import replace
import struct
import zlib

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from tighten_synthetic_acceptance import confirmed, locked, require_stopped, compare_case, rollback_detected


class SyntheticAcceptanceTests(unittest.TestCase):
    def test_confirmed_not_pending(self):
        fw = dict(CURRENT="A", CONFIRMED="A", PENDING="-", ATTEMPTS="0", ACTIVE="0", HTRIAL="0")
        self.assertTrue(confirmed(fw, "A"))
        for key, value in dict(CURRENT="B", CONFIRMED="B", PENDING="A", ATTEMPTS="1", ACTIVE="1", HTRIAL="1").items():
            self.assertFalse(confirmed({**fw, key: value}, "A"))

    def test_all_power_off_fields_required(self):
        safe = dict(LATCHED="1", SD="0", MOE="0", FOC="0")
        self.assertTrue(locked(safe))
        for key in safe:
            self.assertFalse(locked({k: v for k, v in safe.items() if k != key}))

    def test_rollback_requires_a_confirmed_opposite_slot(self):
        fw = dict(CURRENT="B", CONFIRMED="B", PENDING="-", ATTEMPTS="0", ACTIVE="0", HTRIAL="0")
        self.assertTrue(rollback_detected(fw, "A"))
        self.assertFalse(rollback_detected(fw, "B"))
        for key in ("CURRENT", "CONFIRMED", "PENDING", "ATTEMPTS", "ACTIVE", "HTRIAL"):
            self.assertFalse(rollback_detected({k: v for k, v in fw.items() if k != key}, "A"))
        self.assertFalse(rollback_detected({k: v for k, v in fw.items() if k not in ("CURRENT", "CONFIRMED")}, "A"))

    def test_diagnostic_requires_exact_a_and_unchanged_protected_regions(self):
        from tighten_synthetic_diagnose_trial import verify_existing
        image = struct.pack("<II", 0x2001FFF8, 0x08008009) + bytes(range(64))
        before = bytes(0x80000)

        def actual(size=0, crc=0, confirmed_slot=2, pending=0):
            data = bytearray(before)
            data[0x8000:0x8000 + len(image)] = image
            words = (0x424F4F54, 3, confirmed_slot, pending, 0, 346, size, crc, 8, 0, 0)
            meta = struct.pack("<11I", *words)
            data[0x7E800:0x7E830] = meta + struct.pack("<I", zlib.crc32(meta))
            return data

        verify_existing(before, actual(), image)  # Retired A: full bytes still independently verified.
        verify_existing(before, actual(len(image), zlib.crc32(image)), image)
        for address in (0, 0x8000, 0x40000, 0x78000, 0x7F800):
            changed = actual()
            changed[address] ^= 1
            with self.assertRaises(RuntimeError):
                verify_existing(before, changed, image)
        for changed in (actual(len(image), 1), actual(0, 1), actual(confirmed_slot=1), actual(pending=1)):
            with self.assertRaises(RuntimeError):
                verify_existing(before, changed, image)

    def test_stopped_bench_rejects_each_live_output(self):
        text = "OK BENCH ACTIVE=0 LOCK=1 SD=0 MOE=0 CCER=0 CEN=0"
        require_stopped(text)
        for key in ("ACTIVE", "SD", "MOE", "CCER", "CEN"):
            with self.assertRaises(RuntimeError):
                require_stopped(text.replace(key + "=0", key + "=1"))

    def test_parity_never_accepts_wrong_outcome_or_model_bit(self):
        r = dict(OUT="MODEL_OK", TARGET="2000000", TRUTH="1", TRANS="4", OFF="1",
                 MODEL="1", MAXMA="246", MS="7590", STEPS="15680", FINAL="1913643", PEAK="1913643")
        compare_case(r, r)
        for key, value in dict(OUT="PROCESS_OK", MODEL="0", OFF="0", MAXMA="247", MS="7620",
                               STEPS="15730", FINAL="1940000", PEAK="1940000").items():
            with self.assertRaises(RuntimeError):
                compare_case({**r, key: value}, r)

    def test_native_model_matches_python_without_noise(self):
        from tighten_synthetic_acceptance import host_results, ROOT
        executable = ROOT / "tests/tighten_synthetic_host/build/tighten_synthetic_test.exe"
        if not executable.exists():
            self.skipTest("Build the native host fixture first")
        sys.path.insert(0, str(ROOT / "simulation/tightening"))
        from model import load_firmware_profile, simulate
        from run import cases
        refs = host_results(executable)
        profile = load_firmware_profile()
        for case, (_, (assumptions, recipe)) in enumerate(cases().items()):
            for mode, controller in enumerate(("baseline", "feedback")):
                with self.subTest(case=case, mode=mode):
                    result = simulate(profile, replace(assumptions, torque_noise_nm=0),
                                      recipe, controller, keep_trace=False)
                    native = refs[case, mode]
                    self.assertEqual(native["OUT"], result.outcome)
                    self.assertLess(abs(int(native["FINAL"]) / 1e9 - result.final_true_torque_nm), 0.00002)

    def test_normal_main_unchanged_when_fixture_is_off(self):
        from tighten_synthetic_acceptance import ROOT
        from test_foc_current_zero import without_test_profiles
        for slot in ("a", "b"):
            original = ROOT / f"safety_backups/tighten-synthetic-20261008/before_{slot}_main.c"
            if not original.exists():
                self.skipTest("Local pre-edit source snapshot is not available")
            current = (ROOT / f"foc2_app_{slot}/Core/Src/main.c").read_text(encoding="utf-8")
            self.assertEqual(without_test_profiles(current),
                             without_test_profiles(original.read_text(encoding="utf-8")))

    def test_normal_startup_unchanged_when_fixture_is_off(self):
        from tighten_synthetic_acceptance import ROOT
        for slot in ("a", "b"):
            original = ROOT / f"safety_backups/tighten-synthetic-20261008/before_{slot}_startup.s"
            if not original.exists():
                self.skipTest("Local pre-edit assembly snapshot is not available")
            current = (ROOT / f"foc2_app_{slot}/startup_stm32g474xx.s").read_text(encoding="utf-8")
            output, depth = [], 0
            for row in current.splitlines(keepends=True):
                if row.strip() == "#if defined(TIGHTEN_SYNTHETIC_BENCH)":
                    self.assertEqual(depth, 0)
                    depth = 1
                elif depth and row.strip() == "#endif":
                    depth = 0
                elif not depth:
                    output.append(row)
            self.assertEqual(depth, 0)
            # EOF blank-line normalization is not an instruction change.
            # Keep every other character/line identical, including vector table.
            self.assertEqual("".join(output).rstrip("\n"), original.read_text(encoding="utf-8").rstrip("\n"))


if __name__ == "__main__":
    unittest.main()
