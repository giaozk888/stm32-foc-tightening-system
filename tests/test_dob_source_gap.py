"""Simulation-only short-source-gap recovery. Never calls any board tool."""
import ctypes as C
import math
from pathlib import Path
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]
NATIVE = ROOT / 'simulation/dob_simulink/native'
COMMON = ROOT / 'firmware_common'
FLAGS = ['FOC_DOB_SPIKE_ADMISSION=1', 'FOC_DOB_ADMISSION_START_GUARD=1',
         'FOC_DOB_DIRECT_JUMP_REJECT=1', 'FOC_DOB_RECOVERABLE_ADMISSION=1',
         'FOC_DOB_PERSISTENT_QUALITY=1', 'FOC_DOB_ID_PRE_LPF_QUALITY=1',
         'FOC_DOB_NORMAL_CONTROL=1', 'FOC_DOB_CONTACT20_OBSERVE10=1',
         'FOC_DOB_ID_TRACE=1', 'DOB_ADMIT_JUMP_A=.200f', 'DOB_FB_GAIN=dob_host_gain']


class SourceGapTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dlls = []
        for fixed in (False, True):
            path = ROOT / 'tmp' / f'dob-source-gap-unit-{int(fixed)}.dll'
            command = ['D:/Qt/Tools/mingw1310_64/bin/gcc.exe', '-std=c11', '-O2',
                       '-Wall', '-Wextra', '-Werror', '-shared', '-include', str(NATIVE / 'host_compat.h'),
                       '-I', str(COMMON)] + ['-D' + f for f in FLAGS]
            if fixed:
                command.append('-DDOB_OFFLINE_SOURCE_GAP_FIX=1')
            command += [str(NATIVE / 'dob_host.c')] + [str(COMMON / f) for f in
                ('mechanical_dob_monitor.c', 'speed_scurve.c', 'speed_accel_feedforward.c',
                 'speed_friction_compensation.c')] + ['-o', str(path)]
            p = subprocess.run(command, text=True, capture_output=True)
            assert p.returncode == 0, p.stderr
            d = C.CDLL(str(path))
            d.dob_host_reset.argtypes = [C.POINTER(C.c_double)]
            d.dob_host_step.argtypes = [C.c_double, C.POINTER(C.c_double), C.POINTER(C.c_double)]
            d.dob_host_observe.argtypes = [C.POINTER(C.c_double), C.POINTER(C.c_double)]
            d.dob_host_state_size.restype = C.c_uint
            d.dob_host_save.argtypes = d.dob_host_restore.argtypes = [C.c_void_p]
            cls.dlls.append(d)

    def step(self, d, k, u):
        y = (C.c_double * 33)()
        d.dob_host_step(k / 1000, (C.c_double * 10)(*u), y)
        self.assertTrue(all(math.isfinite(x) for x in y))
        return list(y)

    def steady(self, fixed=1):
        d = self.dlls[fixed]
        d.dob_host_reset((C.c_double * 3)(0, 0, .025))
        w = 20
        iq = .0015676864325576986*w + .11945168237076952 + .0005496600325149542 + .02
        u = [w*30/math.pi, w, iq, 0, 0, .005, 1, 0, 0, 1]
        for k in range(3000):
            y = self.step(d, k, u)
        self.assertEqual(y[11], 1)
        return d, u, y

    def test_healthy_path_matches_legacy_exactly(self):
        a, u, _ = self.steady(0)
        b, _, _ = self.steady(1)
        for k in range(3000, 3100):
            self.assertEqual(self.step(a, k, u), self.step(b, k, u))

    def test_three_ms_holds_and_two_real_recovery_endpoints(self):
        d, u, before = self.steady()
        for k in range(3000, 3005):
            u[6] = int(k >= 3003)
            y = self.step(d, k, u)
            self.assertEqual(y[11], 0)
            self.assertEqual(y[15], 0)
            for field in (10, 13, 18, 21, 22, 32):
                self.assertEqual(y[field], before[field], field)
        y = self.step(d, 3005, u)
        self.assertEqual(y[11], 1)
        self.assertEqual(y[18], before[18])
        self.assertLess(y[21]-before[21], .00101)

    def test_long_gap_resets_once_and_rewarms(self):
        d, u, before = self.steady()
        u[6] = 0
        for k in range(3000, 3030):
            y = self.step(d, k, u)
            self.assertEqual(y[11], 0)
        self.assertEqual(y[18]-before[18], 1)
        self.assertEqual(int(y[12]), 16384)
        u[6] = 1
        first = None
        for k in range(3030, 3550):
            y = self.step(d, k, u)
            if first is None and y[11]:
                first = k
        self.assertIsNotNone(first)
        self.assertGreaterEqual(first-3030, 390)

    def test_saturation_and_encoder_time_are_not_held(self):
        for field, value in ((7, 1), (8, 3000)):
            d, u, before = self.steady()
            u[field] = value
            y = self.step(d, 3000, u)
            self.assertEqual(y[11], 0)
            self.assertGreater(y[18], before[18])
            self.assertNotEqual(int(y[12]), 4096)

    def test_snapshot_in_missing_interval_is_complete(self):
        d, u, _ = self.steady()
        u[6] = 0
        self.step(d, 3000, u)
        state = C.create_string_buffer(d.dob_host_state_size())
        d.dob_host_save(state)
        def continuation():
            out = []
            for k in range(3001, 3010):
                u[6] = int(k >= 3003)
                out.append(self.step(d, k, u))
            return out
        expected = continuation()
        d.dob_host_restore(state)
        self.assertEqual(continuation(), expected)

    def test_bad_recovery_point_cannot_pollute_filters(self):
        d, u, before = self.steady()
        u[6] = 0
        self.step(d, 3000, u)
        u[6] = 1
        u[5] = .7
        y = self.step(d, 3001, u)
        self.assertEqual(y[11], 0)
        self.assertEqual(y[15], 0)
        self.assertEqual(y[13], before[13])

    def test_large_speed_change_during_gap_requires_rewarm(self):
        d, u, before = self.steady()
        u[6] = 0
        self.step(d, 3000, u)
        u[6] = 1
        # Speed control LPF sees a source-consistent but discontinuous input.
        u[1] += 11 # Below original 300rpm guard, above recovery quality bound.
        u[0] = 240
        y = self.step(d, 3001, u)
        self.assertEqual(y[29], 0)
        self.assertEqual(y[11], 0)
        self.assertGreater(y[18], before[18])

    def test_recovery_bound_includes_both_confirmation_points(self):
        for missing in (1, 2, 3, 4):
            d, u, before = self.steady()
            for k in range(3000, 3000+missing+3):
                u[6] = int(k >= 3000+missing)
                y = self.step(d, k, u)
            if missing <= 3:
                self.assertEqual(y[11], 1)
                self.assertEqual(y[18], before[18])
            else:
                self.assertEqual(y[11], 0)
                self.assertEqual(y[18]-before[18], 1)

    def test_recovery_across_uint32_source_clock_wrap(self):
        d = self.dlls[1]
        d.dob_host_reset((C.c_double * 3)(0, 0, .025))
        w = 20
        iq = .0015676864325576986*w + .11945168237076952 + .0005496600325149542 + .02
        def observe(k, valid):
            enc = (2**32 - 3003000 + k*1000) % 2**32
            u = [(enc+20) % 2**32, enc, 1000, w, .005, iq, k*20+20,
                 (enc-20) % 2**32, enc, valid, 0, 0, 1, 0]
            y = (C.c_double * 33)()
            d.dob_host_observe((C.c_double * 14)(*u), y)
            return list(y)
        for k in range(3000):
            before = observe(k, 1)
        self.assertEqual(before[11], 1)
        for k in range(3000, 3006):
            y = observe(k, int(k >= 3003))
        self.assertEqual(y[11], 1)
        self.assertEqual(y[18], before[18])


if __name__ == '__main__':
    unittest.main()
