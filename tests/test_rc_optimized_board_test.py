"""Offline-only tests of pinned staging/trial command boundaries."""
import copy
import json
from pathlib import Path
import struct
import unittest
from unittest.mock import patch

import rc_optimized_board_test as board
import test_rc_protected_trial as prior_tests


class OptimizedBoardTests(unittest.TestCase):
    def test_exact_b_and_mailbox(self):
        image = board.pinned_image()
        self.assertEqual(len(image),board.SIZE)
        self.assertEqual(board.mailbox(2,image)[:5],(0x584f424d,1,2,1,2))
        self.assertEqual(board.mailbox(3)[:7],(0x584f424d,1,3,1,1,0,0))
        for command,image in ((1,None),(3,board.pinned_image()),(2,b''),(4,None)):
            with self.assertRaises(ValueError): board.mailbox(command,image)

    def test_recovery_only_existing_a_before_instructions_and_exact_compare(self):
        c = board.recovery_commands(Path('live'),Path('before'),Path('recovered'),0x08008100)
        text = '\n'.join(c)
        self.assertLess(text.index('Live Flash changed'),text.index('reset halt'))
        self.assertLess(text.index('bp 0x8008100 2 hw'),text.index('reset run'))
        self.assertIn('wait_halt 25000',c)
        self.assertEqual(c.count('reset run'),1)
        self.assertFalse(any(v.startswith('flash ') for v in c))
        for v in c:
            if v.startswith('mww ') and '0x2001' in v:
                self.assertTrue(0x2001ffc0 <= int(v.split()[1],16) < 0x2001ffe0)
        for entry in (0,0x08040000,0x08008101):
            with self.assertRaises(ValueError):
                board.recovery_commands(Path('a'),Path('b'),Path('c'),entry)

    def test_stage_only_inactive_b_no_activation(self):
        c = board.stage_commands(Path('live'),Path('baseline'),Path('staged'))
        text = '\n'.join(c)
        self.assertLess(text.index('Live Flash changed'),text.index('reset halt'))
        self.assertLess(text.index('reset halt'),text.index('flash write_image'))
        writes = [v for v in c if v.startswith('flash ')]
        self.assertEqual(len(writes),1)
        self.assertTrue(writes[0].endswith('0x08040000 bin'))
        for forbidden in ('reset run','resume','0x2001FFC0','START'):
            self.assertNotIn(forbidden,text)

    def test_recovered_a_vtor_requires_exact_reset_pc_before_stage(self):
        c = board.stage_commands(Path('live'),Path('baseline'),Path('staged'),0x080168cc)
        text = '\n'.join(c)
        self.assertIn('[mrw 0xE000ED08] != 0x8008000',text)
        self.assertLess(c.index('poll'),next(i for i,v in enumerate(c) if '[reg pc]' in v))
        self.assertLess(text.index('Not at recovered A reset entry'),text.index('Live Flash changed'))
        self.assertLess(text.index('Live Flash changed'),text.index('reset halt'))
        self.assertNotIn('reset run',text)
        with self.assertRaises(ValueError):
            board.stage_commands(Path('a'),Path('b'),Path('c'),0x08040000)

    def test_completed_recovery_accepts_only_exact_known_host_failure(self):
        with self.assertRaises(ValueError):
            board.load_completed_recovery(Path('unrelated.json'))
        prior = json.loads(board.RECOVERY_INTERRUPTION.read_text('utf-8'))
        for key,value in (('programming_attempted',True),('trial_requests',1),('motor_commands',1),
                          ('failure','other error'),('image_sha256','bad')):
            changed = copy.deepcopy(prior)
            changed[key] = value
            with patch.object(board.json,'loads',return_value=changed),self.assertRaises(ValueError):
                board.load_completed_recovery(board.RECOVERY_INTERRUPTION)

    def test_stage_comparison_protects_all_other_pages(self):
        image = board.pinned_image()
        before = bytes([0x55])*0x80000
        actual = bytearray(before)
        end = 0x40000+len(image)
        page_end = (end+0x7ff)&~0x7ff
        actual[0x40000:end] = image
        actual[end:page_end] = b'\xff'*(page_end-end)
        with patch.object(board.old,'latest_meta',return_value=board.FAILED_META):
            board.compare_stage(before,actual,image)
            for offset in (0,0x7fff,0x8000,0x3ffff,end,page_end,0x78000,0x7e800,0x7f800):
                changed = actual.copy()
                changed[offset] ^= 1
                with self.subTest(offset=offset),self.assertRaises(ValueError):
                    board.compare_stage(before,changed,image)

    def test_trial_mailbox_only_and_strict_no_motion_console(self):
        c = board.trial_commands(Path('live'),Path('before'),board.pinned_image())
        text = '\n'.join(c)
        self.assertLess(text.index('Outputs not off'),text.index('Live Flash changed'))
        self.assertLess(text.index('Live Flash changed'),text.index('mww '))
        self.assertEqual(c.count('reset run'),1)
        for v in c:
            self.assertFalse(v.startswith(('flash ','resume','mmw ')))
            if v.startswith('mww '):
                self.assertTrue(0x2001ffc0 <= int(v.split()[1],16) < 0x2001ffe0)
        console = board.previous.Console(None)
        for command in ('START','FW END','RESET','CLEAR','MOTOR TEST SPEED'):
            with self.assertRaises(ValueError): console.query(command)
        self.assertEqual((console.starts,console.ends),(0,0))

    def test_retains_original_failure_and_timing_verdicts(self):
        sample = prior_tests.TrialTests().sample()
        board.previous.validate(copy.deepcopy(sample))
        sample['timing']['MAX_US'] = '50'
        with self.assertRaises(RuntimeError): board.previous.validate(sample)
        failed = json.loads(board.PRIOR.read_text('utf-8'))
        with self.assertRaises(RuntimeError): board.previous.validate(failed['sample'])

    def test_real_output_off_trial_pass_does_not_claim_motor_or_pwm_qualification(self):
        path = board.OUTPUT/'rc-optimized-trial-1792126877053386600.json'
        row = json.loads(path.read_text('utf-8'))
        self.assertIs(row['pass_'],True)
        self.assertIs(row['normally_confirmed'],True)
        self.assertIs(row['compute_50us_pass'],True)
        self.assertGreaterEqual(row['observed_seconds'],30)
        self.assertGreater(row['observed_pairs'],600000)
        self.assertEqual(row['compute_max_us'],44)
        self.assertLess(row['adc_irq_max_us'],50)
        self.assertEqual(row['image_sha256'],board.SHA)
        self.assertEqual(row['trial_requests'],1)
        self.assertEqual((row['host_motor_commands'],row['host_uart_trial_commits']),(0,0))
        self.assertEqual(tuple(row['final_metadata'][2:6]),(2,0,0,570))
        for key in ('final_outputs_off','final_cpu_halted','all_app_and_private_bytes_unchanged'):
            self.assertIs(row[key],True)
        for key in ('rc_software_admission','motor_closed_loop_verified',
                    'physical_pwm_preload_deadline_verified','bridge_analog_settling_verified'):
            self.assertIs(row[key],False)
        for sample in row['samples']:
            board.previous.validate(sample)
            self.assertEqual(sample['commit']['READY'],'0')
            self.assertEqual(sample['commit']['CHECK'],'0')
            self.assertEqual(sample['timing']['LATE'],'0')
        self.assertGreater(int(row['samples'][-1]['commit']['BOTTOM_LATE']),
                           int(row['samples'][0]['commit']['BOTTOM_LATE']))

    def test_trial_final_capture_checks_metadata_and_nonmetadata(self):
        before = bytes(0x80000)
        image = board.pinned_image()
        meta = list(board.FAILED_META)
        meta[2:6] = (2,0,0,570)
        meta[8:10] = (len(image),board.zlib.crc32(image))
        initial = list(board.FAILED_META)
        initial[2:6] = (1,0,0,567)
        with patch.object(board.old,'latest_meta',side_effect=[tuple(meta),tuple(initial)]):
            self.assertEqual(board.compare_final(before,before,image),tuple(meta))
        for offset in (0,0x8000,0x40000,0x78000,0x7f800):
            actual = bytearray(before)
            actual[offset] ^= 1
            with self.assertRaises(ValueError): board.compare_final(before,actual,image)


if __name__ == '__main__': unittest.main()
