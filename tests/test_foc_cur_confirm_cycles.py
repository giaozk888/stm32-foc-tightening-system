"""Offline only: confirmation policy and ISR cost/scope checks, no hardware."""
import re
import unittest
import test_foc_fast_current_reject as fast


class CurConfirmCycles(unittest.TestCase):
    def test_adc_cycle_state_machine_at_os_o2(self):
        fast.OUT.mkdir(exist_ok=True)
        for opt in ('-Os', '-O2'):
            exe = fast.OUT / ('cur_confirm_cycles' + opt + '.exe')
            fast.run(fast.legacy.GCC, '-std=c11', opt, '-Wall', '-Wextra', '-Werror',
                     '-pedantic', '-UNDEBUG', '-I', fast.COMMON, *fast.FLAGS,
                     fast.ROOT / 'tests/foc_cur_confirm_cycles_host.c', '-o', exe)
            self.assertIn('PASS CUR_CONFIRM cycles', fast.run(exe))

    def test_confirmation_has_bounded_work_and_no_io(self):
        text = (fast.COMMON / 'foc_filtered_protection_candidate.h').read_text('utf-8')
        helper = text.split('FocOcConfirmResult FocFp_ConfirmPair(', 1)[1].split(
            '/* Independent RAW', 1)[0]
        code = re.sub(r'/\*.*?\*/', '', helper, flags=re.S)
        self.assertNotRegex(code, r'\b(?:for|while|printf|snprintf|UART_\w+|malloc|free)\s*\(')
        self.assertNotIn('confirm_deadline_us', code)
        self.assertLess(code.index('CUR_CONFIRM_CLEAR_GOOD_SAMPLES'), code.index('CUR_CONFIRM_MAX_CYCLES'))


if __name__ == '__main__':
    unittest.main()
