"""Pinned no-motion trial tests; all inputs local, no device/private I/O."""
import copy
import json
from pathlib import Path
import unittest
from unittest.mock import patch

import rc_protected_trial as trial


class TrialTests(unittest.TestCase):
    def sample(self):
        prior = trial.stage.OUTPUT / 'rc-sampling-trial-1792121761791953100.json'
        row = copy.deepcopy(json.loads(prior.read_text('utf-8'))['samples'][-1])
        row['adaptive']['HARD_OFF'] = '0'
        row['profile'] = dict(NAME='RC_PROTECTED_CANDIDATE', HARD_OFF='0', FSM='ORIGINAL',
                              QUALIFIED='0', RPM='20', LEASE_US='400000')
        row['commit'] = dict(RC='1', READY='0', CHECK='0', FAIL='0',
                             BOTTOM_LATE='26961', GUARD='170', HW_VERIFIED='0')
        return row

    def test_compute_with_closed_admission_is_not_motion_qualification(self):
        trial.validate(self.sample())

    def test_coarse_alarm_cannot_admit_start(self):
        row = self.sample()
        row['commit']['READY'] = '1'
        with self.assertRaisesRegex(RuntimeError, 'did not reject'):
            trial.validate(row)

    def test_no_alarm_may_report_software_admission_but_not_hw_verified(self):
        row = self.sample()
        row['commit'].update(READY='1', BOTTOM_LATE='0')
        trial.validate(row)
        row['commit']['HW_VERIFIED'] = '1'
        with self.assertRaises(RuntimeError):
            trial.validate(row)

    def test_console_rejects_every_motion_or_mutation_command(self):
        console = trial.Console(None)
        for text in ('START', 'MOTOR TEST SPEED', 'FW END', 'RESET', 'CLEAR', 'FW BEGIN 1 12345678'):
            with self.subTest(command=text), self.assertRaises(ValueError):
                console.query(text)
        self.assertEqual(console.starts, 0)
        self.assertEqual(console.ends, 0)

    def test_trial_mailbox_only_after_full_compare_and_off_proof(self):
        image = trial.stage.pinned_image()
        words = trial.mailbox(image)
        self.assertEqual(words[:5], (0x584f424d, 1, 2, 1, 2))
        with self.assertRaises(ValueError):
            trial.mailbox(image[:-1])
        commands = trial.trial_commands(Path('live.bin'), Path('before.bin'), image)
        text = '\n'.join(commands)
        self.assertLess(text.index('Outputs not off'), text.index('Live Flash changed'))
        self.assertLess(text.index('Live Flash changed'), text.index('mww '))
        self.assertEqual(commands.count('reset run'), 1)
        for command in commands:
            self.assertFalse(command.startswith(('flash ', 'resume', 'mmw ')))
            if command.startswith('mww '):
                address = int(command.split()[1], 16)
                self.assertTrue(0x2001ffc0 <= address < 0x2001ffe0)

    def test_final_comparison_rejects_nonmetadata_mutation(self):
        image = trial.stage.pinned_image()
        before = bytes([0x55]) * 0x80000
        meta = list(trial.stage.META)
        meta[5] += 3
        meta[2:5] = (2, 0, 0)
        meta[8:10] = (len(image), trial.zlib.crc32(image))
        with patch.object(trial.stage, 'latest_meta', return_value=tuple(meta)):
            trial.compare_final(before, before, image)
            for offset in (0, 0x8000, 0x40000, 0x78000, 0x7f800):
                actual = bytearray(before)
                actual[offset] ^= 1
                with self.subTest(offset=offset), self.assertRaises(RuntimeError):
                    trial.compare_final(before, actual, image)

    def test_real_failed_trial_cannot_be_reported_as_pass(self):
        path = trial.stage.OUTPUT / 'rc-protected-trial-1792123335544055000.json'
        row = json.loads(path.read_text('utf-8'))
        self.assertFalse(row['pass_'])
        self.assertEqual(row['host_motor_commands'], 0)
        self.assertTrue(row['final_cpu_halted'] and row['final_outputs_off'])
        sample = row['sample']
        self.assertEqual(sample['zero']['STATE'], '3')
        self.assertEqual(sample['state']['FLAGS'], '256')
        self.assertEqual(sample['commit']['READY'], '0')
        with self.assertRaises(RuntimeError):
            trial.validate(sample)


if __name__ == '__main__':
    unittest.main()
