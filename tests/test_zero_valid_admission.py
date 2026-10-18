"""Real zero estimator admission at Os/O2; no device imports or hardware I/O."""
import ctypes
import json
import re
from pathlib import Path
import subprocess
import unittest
from test_pipeline_closed_loop import FLAGS

ROOT = Path(__file__).resolve().parents[1]
GCC = r'D:\Qt\Tools\mingw1310_64\bin\gcc.exe'
COMMON = ROOT / 'firmware_common'


class ZeroValidAdmissionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        out = ROOT / 'tests/zero_valid_admission_build'
        out.mkdir(exist_ok=True)
        cls.libs = []
        for opt, cap in (('Os', 4100), ('O2', 4100), ('Os', 4000)):
            dll = out / f'{opt}_{cap}.dll'
            subprocess.run([GCC, '-std=c11', '-' + opt, '-Wall', '-Wextra',
                '-Werror', '-pedantic', '-shared', *FLAGS,
                '-DFOC_ZERO_VALID_ADMISSION=1', f'-DZERO_CAL_MAX_TOTAL_SAMPLES={cap}',
                '-I', str(COMMON), str(ROOT / 'tests/zero_valid_admission_host.c'),
                *[str(COMMON / f) for f in ('foc_current_zero.c',
                    'foc_zero_median.c', 'foc_zero_robust.c')], '-o', str(dll)], check=True)
            lib = ctypes.CDLL(str(dll))
            lib.zero_push.argtypes = [ctypes.c_uint16, ctypes.c_uint16]
            lib.zero_read.argtypes = [ctypes.POINTER(ctypes.c_uint32)]
            cls.libs.append(lib)

    def read(self, lib):
        out = (ctypes.c_uint32 * 12)()
        lib.zero_read(out)
        return dict(zip(('state', 'valid', 'reject', 'total', 'max_consecutive',
            'zero_u', 'zero_v', 'sum_u', 'sum_v', 'flags', 'reason', 'segments'), out))

    def feed(self, lib, pairs):
        for u, v in pairs:
            lib.zero_push(u, v)
        return self.read(lib)

    def test_A_exactly_4000_normal_pairs(self):
        for lib in self.libs:
            lib.zero_begin()
            self.assertEqual(self.feed(lib, [(1561, 1561)] * 3999)['state'], 2)
            r = self.feed(lib, [(1561, 1561)])
            self.assertEqual((r['state'], r['valid'], r['total'], r['reject']),
                (3, 4000, 4000, 0))
            self.assertEqual((r['zero_u'], r['zero_v'], r['segments']), (1561, 1561, 8))

    def test_B_isolated_spikes_are_rejected_then_replenished(self):
        for lib in self.libs[:2]:
            lib.zero_begin()
            pairs = [(1561, 1561)] * 4010
            for i in range(102, 3103, 500):
                pairs[i] = (1700, 1561)
            r = self.feed(lib, pairs)
            self.assertEqual((r['state'], r['valid'], r['reject']), (3, 4000, 7))
            self.assertEqual(r['sum_u'], 4000 * 1561)
            self.assertEqual(r['sum_v'], 4000 * 1561)
            self.assertEqual(r['max_consecutive'], 1)
            self.assertLessEqual(r['total'] - r['valid'] - r['reject'], 4)

    def test_C_real_failure_window_two_rejects_is_not_fatal(self):
        real = list(zip([1564, 1535, 1565, 1625, 1561],
                        [1570, 1526, 1570, 1646, 1567]))
        for lib in self.libs[:2]:
            lib.zero_begin()
            self.feed(lib, [(1561, 1561)] * 3120)
            r = self.feed(lib, real)
            self.assertEqual((r['state'], r['valid'], r['reject']), (2, 3123, 2))
            self.assertEqual((r['sum_u'], r['sum_v']),
                (3120 * 1561 + 1564 + 1565 + 1561,
                 3120 * 1561 + 1570 + 1570 + 1567))
            r = self.feed(lib, [(1561, 1561)] * 900)
            self.assertEqual((r['state'], r['valid'], r['reject']), (3, 4000, 2))

    def test_D_consecutive_reject_crosses_block_boundary_and_fails(self):
        for lib in self.libs:
            lib.zero_begin()
            r = self.feed(lib, [(1561, 1561)] * 3 + [(1700, 1561)] * 3 +
                [(1561, 1561)] * 4)
            self.assertEqual((r['state'], r['reject'], r['max_consecutive']), (4, 3, 3))
            self.assertEqual(r['flags'], 512)
            self.assertEqual((r['zero_u'], r['zero_v']), (0, 0))

    def test_E_reject_budget_80_allowed_81_fails(self):
        block = [(1561, 1561)] * 2 + [(1700, 1561)] + [(1561, 1561)] * 2
        for lib in self.libs[:2]:
            lib.zero_begin()
            r = self.feed(lib, block * 80 + [(1561, 1561)] * 3700)
            self.assertEqual((r['state'], r['valid'], r['reject']), (3, 4000, 80))
            lib.zero_begin()
            r = self.feed(lib, block * 81)
            self.assertEqual((r['state'], r['reject'], r['flags']), (4, 81, 256))

    def test_F_only_accepted_raw_pairs_enter_both_offset_sums(self):
        for lib in self.libs[:2]:
            for spike in (1200, 1900):
                lib.zero_begin()
                # IV-only spike must reject the WHOLE physical pair (including IU).
                block = [(1560, 1561), (1561, 1562), (1590, spike),
                         (1562, 1563), (1563, 1564)]
                self.feed(lib, block * 10)
                r = self.feed(lib, [(1561, 1561)] * 4000)
                self.assertEqual((r['state'], r['valid'], r['reject']), (3, 4000, 10))
                self.assertEqual(r['sum_u'], 10 * (1560 + 1561 + 1562 + 1563) + 3960 * 1561)
                self.assertEqual(r['sum_v'], 10 * (1561 + 1562 + 1563 + 1564) + 3960 * 1561)

    def test_total_limit_is_independent_and_bounded(self):
        lib = self.libs[2]
        lib.zero_begin()
        r = self.feed(lib, [(1700, 1561)] + [(1561, 1561)] * 3999)
        self.assertEqual((r['state'], r['valid'], r['total'], r['flags']),
            (4, 3999, 4000, 1024))

    def test_persistent_shift_invalid_adc_and_segment_drift_still_fail(self):
        for lib in self.libs:
            for pairs, flag in (([(1800, 1800)] * 5, 2), ([(4096, 1561)], 1),
                ([(1561, 1561)] * 500 + [(1567, 1567)] * 500, 128)):
                lib.zero_begin()
                r = self.feed(lib, pairs)
                self.assertEqual((r['state'], r['flags']), (4, flag))
                self.assertEqual((r['zero_u'], r['zero_v']), (0, 0))

    def test_terminal_state_stays_frozen_until_explicit_begin(self):
        for lib in self.libs:
            for pairs in ([(1561, 1561)] * 4000, [(4096, 1561)]):
                lib.zero_begin()
                r = self.feed(lib, pairs)
                self.assertEqual(self.feed(lib, [(0, 4096)] * 100), r)

    def test_build_preserves_speed_profile_and_limits(self):
        for slot in 'ab':
            presets = json.loads((ROOT / f'foc2_app_{slot}/CMakePresets.json').read_text())
            p = next(x for x in presets['configurePresets'] if x['name'] == 'ZeroValidAdmissionTrial')
            self.assertEqual(p['inherits'], 'SpeedStartupBrakeTrial')
            self.assertEqual(p['cacheVariables']['FOC_ZERO_VALID_ADMISSION'], 'ON')

    def test_actual_protected_binding_foreground_report_and_failure(self):
        for opt in ('Os', 'O2'):
            exe = ROOT / f'tests/zero_valid_admission_build/binding_{opt}.exe'
            subprocess.run([GCC, '-std=c11', '-' + opt, '-Wall', '-Wextra',
                '-Werror', '-pedantic', '-UNDEBUG', *FLAGS,
                '-DFOC_ZERO_VALID_ADMISSION=1', '-DFOC_HEAVY_PROFILE_ENABLE=0',
                '-I', str(COMMON), str(ROOT / 'tests/zero_valid_admission_binding_host.c'),
                *[str(COMMON / f) for f in ('foc_current_zero.c',
                    'foc_zero_median.c', 'foc_zero_robust.c')], '-o', str(exe)], check=True)
            result = subprocess.run([str(exe)], check=True, capture_output=True, text=True)
            self.assertIn('PASS zero admission protected binding', result.stdout)

    def test_no_new_arm_compiler_warnings_against_speed_candidate(self):
        for slot in 'ab':
            root = ROOT / f'foc2_app_{slot}/build'
            warnings = {}
            for profile in ('SpeedStartupBrakeTrial', 'ZeroValidAdmissionTrial'):
                commands = json.loads((root / profile / 'compile_commands.json').read_text())
                found = set()
                for source in ('/Core/Src/main.c', '/foc_zero_robust.c', '/foc_zero_median.c'):
                    cmd = next(x['command'] for x in commands if x['file'].endswith(source))
                    p = subprocess.run(re.sub(r' -o \S+ -c ', ' -fsyntax-only ', cmd),
                        cwd=root / profile, capture_output=True, text=True)
                    self.assertEqual(p.returncode, 0, p.stderr)
                    found.update(re.findall(r'warning: (.*)', p.stderr))
                warnings[profile] = found
            self.assertFalse(warnings['ZeroValidAdmissionTrial'] - warnings['SpeedStartupBrakeTrial'], warnings)


if __name__ == '__main__':
    unittest.main()
