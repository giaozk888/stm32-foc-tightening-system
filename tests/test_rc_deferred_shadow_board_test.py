"""Test the device runner's refusal paths without devices or private data."""
import copy
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
import rc_deferred_shadow_board_test as runner


class ShadowBoardRunnerTests(unittest.TestCase):
    def healthy(self):
        return dict(profile=dict(NAME='RC_DEFERRED_SHADOW',ADMISSION='0'),
            commit=dict(READY='0'),
            state=dict(STATE='1',USED='0',QUEUED='0',ARMED='1',ZERO='3',
                FAULT='0',FLAGS='0',SD='0',MOE='0',CCER='0',QUALIFIED='0'),
            zero=dict(STATE='3',REASON='0'),
            timing=dict(CLOCK_HZ='1000000',MAX_US='44',LATE='0',WORK='5000',
                OUTER='1000',IRQ='10000',LEASE_US='400000',SAMPLE_US='100',OUTER_US='2000'),
            protection=dict(FILTER='TREND4',OC='2_OF_3',TRIP_MA='4000',STATE='0',
                REASON='0',FLAGS='0',BUDGET='6',STREAK='4'),
            adc=dict(DWT='1',MAX_CYC='7553',MISS='0',PF='0'),
            fault=dict(VALID='0'),buffer=dict(STK_VALID='1',FREE_B='1000'),
            deferred=dict(SHADOW='1',ADMISSION='0',PUBLISH='0',STALE='0',UNSAFE='0',
                REJECTED='0',PLAN_FAIL='0',STAGED='5001',TAKEN='5000',VALID='1'))

    def test_accepts_handoff_and_rejects_fault_stale_deadline_and_publish(self):
        row = self.healthy()
        runner.validate_sample(row)
        for group,key,value in (('deferred','STALE','1'),('deferred','PUBLISH','1'),
            ('deferred','TAKEN','4999'),('deferred','VALID','0'),
            ('deferred','PLAN_FAIL','1'),('protection','REASON','9'),
            ('state','MOE','1'),('timing','MAX_US','50'),('fault','VALID','1'),
            ('adc','MAX_CYC','8500'),('buffer','FREE_B','0')):
            changed = copy.deepcopy(row)
            changed[group][key] = value
            with self.subTest(group=group,key=key),self.assertRaises(RuntimeError):
                runner.validate_sample(changed)

    def test_stage_writes_only_inactive_a_after_full_compare_without_run(self):
        commands = runner.stage_commands(Path('live.bin'),Path('base.bin'),Path('out.bin'))
        joined = '\n'.join(commands)
        self.assertLess(joined.index('Live Flash changed'),joined.index('flash write_image'))
        writes = [c for c in commands if c.startswith('flash ')]
        self.assertEqual(len(writes),1)
        self.assertTrue(writes[0].endswith('0x08008000 bin'))
        self.assertNotIn('reset run',joined)
        self.assertNotIn('resume',joined)

    def test_outside_erase_page_corruption_rejected(self):
        data = runner.image()
        before = b'\x55'*0x80000
        actual = bytearray(before)
        end = 0x8000+len(data)
        page_end = (end+0x7ff)&~0x7ff
        actual[0x8000:end] = data
        actual[end:page_end] = b'\xff'*(page_end-end)
        with patch.object(runner,'latest_meta',return_value=runner.BASE_META):
            runner.compare_stage(before,actual,data)
            for offset in (0,0x7fff,page_end,0x40000,0x7e800,0x7f800):
                changed = actual.copy()
                changed[offset] ^= 1
                with self.subTest(offset=offset),self.assertRaises(ValueError):
                    runner.compare_stage(before,changed,data)

    def test_console_rejects_motor_and_upgrade_commands(self):
        uart = object.__new__(runner.Console)
        for command in ('START','MOTOR TEST SPEED','FW END','CLEAR_FAULT'):
            with self.subTest(command=command),self.assertRaises(ValueError):
                uart.query(command)


if __name__ == '__main__': unittest.main()
