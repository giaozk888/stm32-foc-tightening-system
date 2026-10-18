"""Loaded original-FSM lease: host register mocks only; no device imports."""
import unittest
import test_pipeline_closed_loop as pipeline


class LoadedFsmTrialTests(unittest.TestCase):
    def test_pipeline_protection_and_loaded_lease(self):
        fast = pipeline.fast
        for opt in ('-Os', '-O2'):
            exe = fast.OUT / ('loaded_fsm_' + opt + '.exe')
            fast.run(fast.legacy.GCC, '-std=c11', opt, '-Wall', '-Wextra',
                     '-Werror', '-pedantic', '-UNDEBUG', '-I', fast.COMMON,
                     *pipeline.FLAGS, '-DFOC_LOADED_FSM_TRIAL=1',
                     '-DFOC_HEAVY_PROFILE_ENABLE=0',
                     pipeline.ROOT / 'tests/foc_pipeline_closed_loop_host.c',
                     fast.COMMON / 'foc_current_zero.c',
                     fast.COMMON / 'foc_zero_median.c',
                     fast.COMMON / 'foc_zero_robust.c', '-o', exe)
            for case in range(25):
                with self.subTest(opt=opt, case=case):
                    self.assertIn('PASS protected pipeline', fast.run(exe, case))


if __name__ == '__main__':
    unittest.main()
