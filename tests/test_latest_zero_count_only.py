"""Count-only zero policy: production C, mocked adapter, and linked identities.

Synthetic inputs are software tests, not evidence of electrical safety or
motor/current accuracy. No serial/debugger or hardware access.
"""
import json
import subprocess
import unittest

import test_latest_original_fsm as latest
from test_foc_adaptive_filter import replay

FLAGS = latest.FLAGS + ['-DFOC_LATEST_ZERO_COUNT_ONLY=1']
PRESET = 'LatestFeedbackOriginalFsmCountOnly'


class CountOnlyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        latest.OUT.mkdir(exist_ok=True)
        cls.exes = {}
        for name, flags in [('bounded', latest.FLAGS), ('count_only', FLAGS)]:
            exe = latest.OUT / ('latest_zero_' + name + '.exe')
            latest.run(latest.GCC, '-std=c11', '-O2', '-Wall', '-Wextra', '-Werror',
                '-pedantic', '-UNDEBUG', '-I', latest.COMMON, *flags,
                latest.ROOT / 'tests/foc_adaptive_replay.c',
                latest.COMMON / 'foc_zero_median.c', latest.COMMON / 'foc_zero_robust.c',
                latest.COMMON / 'foc_current_zero.c', '-o', exe)
            cls.exes[name] = exe

    def zero(self, values, mode='count_only'):
        return replay(self.exes[mode], values, '--zero-window')

    def test_only_total_count_trip_removed(self):
        for count in (20, 21, 80):
            values = [(1560, 1560)] * 4000
            for i in range(count):
                values[10 + i * 10] = (1800, 1800)
            new = self.zero(values)
            self.assertEqual((new['state'], new['count'], new['zero'], new['segments'],
                new['outliers'], new['robust_flags']), (3, 4000, [1560, 1560], 8, count, 0))
            old = self.zero(values, 'bounded')
            self.assertEqual(old['state'], 3 if count <= 20 else 4)
            self.assertEqual(old['robust_flags'], 0 if count <= 20 else 8)

    def test_burst_invalid_nominal_and_drift_still_fail(self):
        burst = [(1560, 1560)] * 4000
        burst[101] = burst[102] = (1800, 1560)
        invalid = [(1560, 1560)] * 4000
        invalid[100] = (5000, 1560)
        for values, flag in [(burst, 4), (invalid, 1), ([(1800, 1800)] * 4000, 2),
            ([(1560 + i // 500, 1560) for i in range(4000)], 128)]:
            z = self.zero(values)
            self.assertEqual((z['state'], z['zero']), (4, [0, 0]))
            self.assertTrue(z['robust_flags'] & flag, z)

    def test_full_physical_window_required(self):
        z = self.zero([(1560, 1560)] * 3999)
        self.assertEqual((z['state'], z['zero']), (2, [0, 0]))

    def test_online_filter_is_identical(self):
        values = [(1560 + (300 if i % 71 == 0 else i % 7), 1560) for i in range(1000)]
        self.assertEqual(replay(self.exes['bounded'], values), replay(self.exes['count_only'], values))

    def test_actual_adapter_unchanged_with_count_only_policy(self):
        exe = latest.OUT / 'latest_original_count_only_adapter.exe'
        latest.run(latest.GCC, '-std=c11', '-O2', '-Wall', '-Wextra', '-Werror',
            '-pedantic', '-UNDEBUG', '-I', latest.COMMON, *FLAGS,
            latest.ROOT / 'tests/latest_original_fsm_host.c',
            latest.COMMON / 'foc_current_zero.c', latest.COMMON / 'foc_zero_median.c',
            latest.COMMON / 'foc_zero_robust.c', '-o', exe)
        self.assertIn('PASS', latest.run(exe))

    def test_count_only_rejected_without_latest_profile(self):
        flags = [f for f in FLAGS if f != '-DFOC_LATEST_ORIGINAL_FSM=1']
        p = subprocess.run([str(latest.GCC), '-std=c11', '-fsyntax-only', '-I', str(latest.COMMON),
            *flags, str(latest.ROOT / 'tests/foc_adaptive_replay.c')], capture_output=True)
        self.assertNotEqual(p.returncode, 0)

    def test_linked_count_only_identity_and_preserved_old_profile(self):
        for slot in 'ab':
            folder = latest.ROOT / f'foc2_app_{slot}/build/{PRESET}'
            data = (folder / 'foc2.bin').read_bytes()
            self.assertIn(b'NAME=LATEST_ORIGINAL_FSM HARD_OFF=0 ADAPT=1 FSM=ORIGINAL', data)
            self.assertIn(b'MAX=OFF SEG_MAX=OFF', data)
            self.assertNotIn(b'MAX=20 SEG_MAX=OFF', data)
            self.assertIn(b'USE_ORIGINAL_START', data)
            self.assertIn(b'TRIP_MA=4000', data)
            self.assertIn(b'FOC_LATEST_ZERO_COUNT_ONLY:BOOL=ON', (folder / 'CMakeCache.txt').read_bytes())
            self.assertLess(len(data), 224 * 1024)
            old = (latest.ROOT / f'foc2_app_{slot}/build/LatestFeedbackOriginalFsm/foc2.bin').read_bytes()
            self.assertIn(b'MAX=20 SEG_MAX=OFF', old)


if __name__ == '__main__':
    unittest.main()
