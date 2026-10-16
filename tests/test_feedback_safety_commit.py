"""Offline command/evidence contracts, never access hardware."""
from pathlib import Path
import sys
import unittest
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
import feedback_safety_commit as tool

class GuardianCommitTests(unittest.TestCase):
    def test_forbidden_commands_and_no_second_end_or_injection(self):
        class Port:
            def write(self, wire): raise AssertionError('Forbidden command reached UART')
        uart=tool.Console(Port())
        for cmd in ('START','CLEAR','BOOT B','BENCH RUN','SWITCH START BRIDGE','FW CONFIRM','FW ABORT'):
            with self.assertRaises(ValueError): uart.query(cmd)
            with self.assertRaises(ValueError): uart.command(cmd)
        uart.ends=1
        with self.assertRaises(ValueError): uart.command('FW END')
        uart.timeout_tests=1
        with self.assertRaises(ValueError): uart.query('BENCH PROTECTION TEST TIMEOUT')

    def test_healthy_evidence_required(self):
        healthy='OK HARD_OFF=1 MOTOR_QUALIFIED=0 RAW=VALIDITY_ONLY FILTERED=2_OF_3 GUARD_US=25 STATE=0 REASON=0 FLAGS=0 ARMED=1 ZERO=1'
        tool.protection(healthy)
        for old,new in (('STATE=0','STATE=2'),('ZERO=1','ZERO=0'),('FLAGS=0','FLAGS=32'),('HARD_OFF=1','HARD_OFF=0')):
            with self.assertRaises(RuntimeError): tool.protection(healthy.replace(old,new))
        good='OK MOTOR_QUALIFIED=0 CLOCK_HZ=1000000 SCOPE=PAIR_CHECK_TO_FOC_END LATE=0 BUDGET_US=50 TEST_USED=0 N=100 MAX_US=25'
        tool.timing(good)
        for old,new in (('LATE=0','LATE=1'),('MAX_US=25','MAX_US=50'),('N=100','N=0')):
            with self.assertRaises(RuntimeError): tool.timing(good.replace(old,new))

    def test_stopped_stream_proof_not_software_fault_banner_alone(self):
        state='OK HARD_OFF=1 MOTOR_QUALIFIED=0 RAW=VALIDITY_ONLY FILTERED=2_OF_3 GUARD_US=25 STATE=2 REASON=6 ARMED=0 ZERO=0'
        fault='OK MOTOR_QUALIFIED=0 VALID=1 REASON=6 SD=0 BDTR=02002055 CCER=00000000 CR1=00000020 OFF_US=225 LAST_VALID_US=100 GUARD_IRQ=100'
        row=tool.timeout_result(state,fault,'OK TEST_USED=1')
        self.assertEqual(row['register_mark_delay_us'],125)
        self.assertFalse(row['physical_shutdown_timing_verified'])
        for old,new in (('SD=0','SD=1'),('CCER=00000000','CCER=00000555'),
                        ('BDTR=02002055','BDTR=0200A055'),('OFF_US=225','OFF_US=100'),
                        ('OFF_US=225','OFF_US=300'),('VALID=1','VALID=0')):
            with self.assertRaises(RuntimeError): tool.timeout_result(state,fault.replace(old,new),'OK TEST_USED=1')
        with self.assertRaises(RuntimeError): tool.timeout_result(state,fault,'OK TEST_USED=0')

    def test_commit_snapshot_before_single_end_and_no_direct_write(self):
        src=Path(tool.__file__).read_text('utf-8')
        self.assertLess(src.index("capture('precommit')"),src.index("uart.command('FW END'"))
        self.assertEqual(src.count("uart.command('FW END'"),1)
        self.assertNotIn("'-rst'",src)
        self.assertNotIn("'-w'",src)
        self.assertIn("capture('final')",src)
        self.assertIn('physical_shutdown_timing_verified=False',src)

if __name__=='__main__': unittest.main()
