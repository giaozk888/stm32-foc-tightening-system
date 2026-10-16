"""Host-only admission tests; fixtures are not hardware acceptance evidence."""
import copy
import struct
import unittest
import zlib

import latest_original_fsm_acceptance as acceptance
import latest_original_fsm_stage as stage


def healthy():
    return dict(
        state=dict(SD='0', MOE='0', CCER='0', FLAGS='0', FAULT='0', QUALIFIED='0',
            STATE='1', USED='0', QUEUED='0', ARMED='1', ZERO='3'),
        timing=dict(CLOCK_HZ='1000000', LATE='0', MAX_US='49', WORK='1001',
            OUTER='101', IRQ='1001', LEASE_US='400000', SAMPLE_US='100', OUTER_US='2000'),
        protection=dict(FILTER='TREND4', OC='2_OF_3', TRIP_MA='4000', STATE='0',
            REASON='0', FLAGS='0', BUDGET='6', STREAK='4'),
        adc=dict(DWT='1', MISS='0', PF='0', MAX_CYC='8330', PAIRS='1001'),
        encoder_dma=dict(FAIL='0', TIMEOUT='0', IO='0', SCHED='0', STALE='0', READS='101'),
        encoder_irq=dict(VALID='0', MAX_LATE_US='1'), encoder_snapshot=dict(VALID='0'),
        cost=dict(TRIG='POLY9_8', DWT='1', CPU_MAX_CYC='7000', PREEMPT_MAX_CYC='1',
            PAIR_MAX_US='1', MATH_MAX_US='42'),
        late_frame=dict(PATH='PAIR2', VALID='0', SEQ='0', US='0', PAIR_US='0',
            MATH_US='0', WALL_CYC='0', IRQ_CYC='0'),
        profile=dict(NAME='LATEST_ORIGINAL_FSM', HARD_OFF='0', ADAPT='1', FSM='ORIGINAL',
            ZERO='BOUNDED', LOCAL='1', RPM='20', LEASE_US='400000', QUALIFIED='0'),
        ram=dict(ENABLED='1', HARD_OFF='0', DEADLINE_US='50'),
        compact=dict(ENABLED='1', HARD_OFF='0', FIXED_OPS='1', GUARD_US='25', DEADLINE_US='50'),
        zero=dict(STATE='3', REASON='0', N='4000'),
        buffer=dict(STK_VALID='1', FREE_B='256', DONE='1'),
        fault=dict(VALID='0'), status='OK STATUS FLT=0')


class AdmissionTests(unittest.TestCase):
    adaptive = dict(ADAPT='1', HARD_OFF='0', DELAY_PAIRS='1')
    robust = dict(BLOCK='5', SEGMENT='500', MAX='20', HARD_OFF='0', FLAGS='0')

    def test_healthy_fixture(self):
        acceptance.validate(healthy(), self.adaptive, self.robust)

    def test_reject_each_gate(self):
        for section, key, value in [('profile', 'FSM', 'OTHER'), ('profile', 'ADAPT', '0'),
            ('state', 'USED', '1'), ('timing', 'MAX_US', '50'), ('adc', 'MISS', '1'),
            ('encoder_dma', 'TIMEOUT', '1'), ('zero', 'REASON', '1'),
            ('protection', 'TRIP_MA', '8000'), ('fault', 'VALID', '1')]:
            with self.subTest(section=section, key=key):
                row = healthy()
                row[section][key] = value
                with self.assertRaises(RuntimeError):
                    acceptance.validate(row, self.adaptive, self.robust)

    def test_reject_disabled_zero_budget_and_filter(self):
        for key, value in [('MAX', 'OFF'), ('HARD_OFF', '1'), ('FLAGS', '1')]:
            r = {**self.robust, key: value}
            with self.assertRaises(RuntimeError):
                acceptance.validate(healthy(), self.adaptive, r)
        with self.assertRaises(RuntimeError):
            acceptance.validate(healthy(), {**self.adaptive, 'DELAY_PAIRS': '2'}, self.robust)

    def test_explicit_count_only_policy_is_distinct_from_historical_default(self):
        robust = {**self.robust, 'MAX': 'OFF', 'OUTLIERS': '80'}
        acceptance.validate(healthy(), self.adaptive, robust, expected_total_limit='OFF')
        with self.assertRaises(RuntimeError):
            acceptance.validate(healthy(), self.adaptive, robust)
        with self.assertRaises(RuntimeError):
            acceptance.validate(healthy(), self.adaptive, self.robust, expected_total_limit='OFF')
        with self.assertRaises(RuntimeError):
            acceptance.validate(healthy(), self.adaptive, {**robust, 'FLAGS': '4'}, expected_total_limit='OFF')
        with self.assertRaises(ValueError):
            acceptance.validate(healthy(), self.adaptive, robust, expected_total_limit='OTHER')

    def test_mailbox_exact_image_and_crc(self):
        image = stage.pinned_image()
        for words in [stage.mailbox(3, 1, 1),
            stage.mailbox(2, 1, 2, len(image), zlib.crc32(image))]:
            self.assertEqual(words[-1], zlib.crc32(struct.pack('<7I', *words[:7])))
        for args in [(3, 2, 2), (1, 2, 2), (2, 1, 2, 8, 0)]:
            with self.assertRaises(ValueError):
                stage.mailbox(*args)

    def test_console_rejects_motion_and_clear(self):
        uart = object.__new__(acceptance.Console)
        for command in ('START', 'MOTOR TEST SPEED', 'CLEAR', 'FW END', 'SET RUNDOWN_RPM 120'):
            with self.assertRaises(ValueError):
                uart.query(command)


if __name__ == '__main__':
    unittest.main()
