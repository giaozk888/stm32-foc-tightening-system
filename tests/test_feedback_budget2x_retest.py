"""Reset-only retest contracts; no hardware access."""
from pathlib import Path
import sys
import unittest
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
import feedback_budget2x_retest as tool

class ResetOnlyTests(unittest.TestCase):
    def test_only_confirmed_exact_generation(self):
        line='OK FW CURRENT=B CONFIRMED=B PENDING=- ATTEMPTS=0 ACTIVE=0 GEN=457'
        tool.require_b457(line)
        for old,new in (('GEN=457','GEN=458'),('CONFIRMED=B','CONFIRMED=A'),
                        ('PENDING=-','PENDING=B'),('ACTIVE=0','ACTIVE=1')):
            with self.assertRaises(RuntimeError): tool.require_b457(line.replace(old,new))
    def test_no_commit_or_start(self):
        class Port:
            def write(self,_): raise AssertionError('Forbidden UART write')
        uart=tool.Console(Port())
        for cmd in ('FW END','FW BEGIN 123 12345678','START','BENCH RUN','CLEAR','BOOT A'):
            with self.assertRaises(ValueError): uart.command(cmd)
            with self.assertRaises(ValueError): uart.query(cmd)
    def test_rate_requires_compute_and_guard_progress(self):
        before=dict(IRQ='100',FEEDBACK_N='100')
        after=dict(IRQ='200100',FEEDBACK_N='100100')
        self.assertEqual(tool.feedback_rate(before,after,5),20000)
        for changed in (dict(IRQ='100',FEEDBACK_N='100100'),dict(IRQ='200100',FEEDBACK_N='100')):
            with self.assertRaises(RuntimeError): tool.feedback_rate(before,changed,5)
    def test_one_reset_no_writes_and_prior_failure_retained(self):
        src=Path(tool.__file__).read_text('utf-8')
        self.assertEqual(src.count("cli('-rst')"),1)
        self.assertIn("if row['resets_attempted']: raise ValueError",src)
        self.assertLess(src.index('verified_baseline(before)'),src.index("cli('-rst')"))
        self.assertIn("capture('final')!=before",src)
        self.assertIn('prior_trial_pass=False',src)
        self.assertNotIn("'-w'",src)
        self.assertNotIn("uart.command(",src)

if __name__=='__main__': unittest.main()
