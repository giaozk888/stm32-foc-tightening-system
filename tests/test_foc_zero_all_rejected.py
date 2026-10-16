"""Offline-only comparison; changed burst policy cannot enable the bridge."""
import subprocess
import unittest

import test_latest_original_fsm as host
import test_foc_adaptive_filter as adaptive

FLAGS = adaptive.ADAPT + ['-DFOC_ZERO_TOTAL_BUDGET_OFF=1', '-DFOC_ZERO_ALL_REJECTED_DIAG=1']


class AllRejectedTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        host.OUT.mkdir(exist_ok=True)
        cls.exes = []
        for opt in ('-Os', '-O2'):
            exe = host.OUT / ('zero_all_rejected' + opt + '.exe')
            host.run(host.GCC, '-std=c11', opt, '-Wall', '-Wextra', '-Werror', '-pedantic',
                '-UNDEBUG', '-I', host.COMMON, *FLAGS,
                host.ROOT / 'tests/foc_adaptive_replay.c', host.COMMON / 'foc_zero_median.c',
                host.COMMON / 'foc_zero_robust.c', host.COMMON / 'foc_current_zero.c', '-o', exe)
            cls.exes.append(exe)

    def zero(self, values):
        results = [adaptive.replay(exe, values, '--zero-window') for exe in self.exes]
        self.assertEqual(results[0], results[1])
        return results[0]

    def test_zero_to_four_rejected_pairs_and_full_window(self):
        blocks = [
            [(1560, 1560)] * 5,
            [(1800, 1560)] + [(1560, 1560)] * 4,
            [(1800, 1560)] * 2 + [(1560, 1560)] * 3,
            [(1560, 1800), (1560, 1560), (1560, 1560), (1800, 1560), (1800, 1560)],
            [(1560, 1800), (1560, 1800), (1560, 1560), (1800, 1560), (1800, 1560)],
        ]
        for rejected, block in enumerate(blocks):
            with self.subTest(rejected=rejected):
                z = self.zero(block * 800)
                self.assertEqual((z['state'], z['count'], z['zero'], z['segments'],
                    z['robust_flags'], z['outliers']), (3, 4000, [1560, 1560], 8, 0, rejected * 800))
        z = self.zero(blocks[4] * 799 + blocks[4][:4])
        self.assertEqual((z['state'], z['zero']), (2, [0, 0]))

    def test_all_pairs_rejected_using_different_channel_medians(self):
        block = [(1400, 1560), (1480, 1400), (1560, 1480), (1640, 1640), (1720, 1720)]
        z = self.zero([(1560, 1560)] * 100 + block)
        self.assertEqual((z['state'], z['count'], z['robust_flags'], z['zero']), (4, 100, 4, [0, 0]))
        self.assertEqual(z['outliers'], 5)

    def test_other_validity_and_drift_checks_retained(self):
        cases = [([(1800, 1800)] * 4000, 2),
            ([(1500, 1500)] * 5 + [(1620, 1620)] * 5, 64),
            ([(1560 + i // 500, 1560) for i in range(4000)], 128),
            ([(1560, 1560)] * 100 + [(5000, 1560)], 1)]
        for values, flag in cases:
            z = self.zero(values)
            self.assertEqual((z['state'], z['zero']), (4, [0, 0]))
            self.assertTrue(z['robust_flags'] & flag, z)

    def test_illegal_control_or_incomplete_profile_rejected(self):
        invalid = [host.FLAGS + ['-DFOC_ZERO_ALL_REJECTED_DIAG=1'],
            adaptive.ADAPT + ['-DFOC_ZERO_ALL_REJECTED_DIAG=1'],
            ['-DFOC_ZERO_ALL_REJECTED_DIAG=1'], FLAGS + ['-DFOC_LATEST_ORIGINAL_FSM=1']]
        for flags in invalid:
            result = subprocess.run([str(host.GCC), '-std=c11', '-fsyntax-only',
                '-I', str(host.COMMON), *flags, str(host.COMMON / 'foc_zero_robust.c')],
                capture_output=True)
            self.assertNotEqual(result.returncode, 0)

    def test_actual_binding_does_not_enable_outputs(self):
        for opt in ('-Os', '-O2'):
            exe = host.OUT / ('zero_all_rejected_binding' + opt + '.exe')
            flags = adaptive.prior.GATE + ['-DFOC_ADAPTIVE_FILTER_EXPERIMENT=1',
                '-DFOC_ZERO_TOTAL_BUDGET_OFF=1', '-DFOC_ZERO_ALL_REJECTED_DIAG=1']
            host.run(host.GCC, '-std=c11', opt, '-Wall', '-Wextra', '-Werror', '-pedantic',
                '-UNDEBUG', '-I', host.COMMON, *flags,
                host.ROOT / 'tests/foc_adaptive_binding_host.c', host.COMMON / 'foc_current_zero.c',
                host.COMMON / 'foc_zero_median.c', host.COMMON / 'foc_zero_robust.c', '-o', exe)
            self.assertIn('PASS', host.run(exe))

    def test_linked_diagnostic_identity_and_old_candidates_preserved(self):
        import hashlib
        hashes = ('b9ef16c8561d279e93db06419237d0cb5e81daafe40f964c51e33dd115aae411',
                  '2450f5a6da36c0698690aa2353fd1f76758e4b7401453fb7f361cfab1e72c61b')
        for slot, digest in zip('ab', hashes):
            folder = host.ROOT / f'foc2_app_{slot}/build'
            data = (folder / 'ZeroAllRejectedDiagnostic/foc2.bin').read_bytes()
            self.assertIn(b'DIAGNOSTIC=1 HARD_OFF=1 BURST=ALL_REJECTED', data)
            self.assertIn(b'ADAPT=1 HARD_OFF=1 DELAY_PAIRS=1', data)
            self.assertIn(b'MAX=OFF SEG_MAX=OFF', data)
            self.assertLess(len(data), 224 * 1024)
            old = (folder / 'LatestOriginalStartupEvidence/foc2.bin').read_bytes()
            self.assertEqual(hashlib.sha256(old).hexdigest(), digest)
            self.assertNotIn(b'BURST=ALL_REJECTED', old)


if __name__ == '__main__':
    unittest.main()
