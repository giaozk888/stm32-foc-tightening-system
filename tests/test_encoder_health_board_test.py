"""Offline image/phase gates for health-synchronized board runner."""
import json
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
import encoder_health_board_test as board


class EncoderHealthBoardTests(unittest.TestCase):
    def test_current_restored_b_baseline_receipt_pin(self):
        row = json.loads(board.BASE_RECEIPT.read_text('utf-8'))
        self.assertTrue(row['pass_'])
        self.assertEqual(row['mode'], 'restore')
        self.assertEqual(row['final_sha256'], board.BASE_SHA)
        self.assertEqual(tuple(row['final_metadata']), board.BASE_META)
        self.assertEqual(board.BASE_META[2:6], (2, 0, 0, 611))
        for key in ('final_outputs_off', 'final_cpu_halted', 'all_app_and_private_bytes_unchanged'):
            self.assertIs(row[key], True)

    def test_exact_health_image_pin(self):
        self.assertEqual(len(board.image()), 228964)
        with patch.object(board,'SHA','0'*64), self.assertRaises(ValueError): board.image()

    def test_matching_schema_and_inactive_page_bounds(self):
        code = ('import encoder_health_board_test as b,json; from unittest.mock import patch; '
                'b.configure(); '
                'assert b.base.wait_confirmation is b.wait_confirmation; '
                'm=patch.object(b.base.tx,"baseline",return_value=(None,b"")); '
                'm.start(); b.previous.verify(); m.stop(); '
                'print(json.dumps(b.base.tx.stage_commands(b.PRIVATE/"live.bin",'
                'b.PRIVATE/"expected.bin",b.PRIVATE/"staged.bin")))')
        p = subprocess.run([sys.executable,'-c',code], cwd=board.ROOT/'tools',
                           capture_output=True,text=True,timeout=30)
        self.assertEqual(p.returncode,0,p.stderr)
        commands = json.loads(p.stdout)
        self.assertTrue(any('EncoderHealthReview/EncoderFocFirst/foc2.bin' in c and
                            '0x08008000 bin' in c for c in commands))
        self.assertTrue(any('verify_image' in c for c in commands))
        self.assertFalse(any(c in ('resume','reset run') or '0x2001FFC0' in c for c in commands))

    def test_power_gate_precedes_device_access(self):
        for mode in ('--stage-inactive-a','--trial-from-stage','--restore-from-trial'):
            args = [mode] + ([] if mode == '--stage-inactive-a' else ['unused.json'])
            p = subprocess.run([sys.executable,str(board.ROOT/'tools/encoder_health_board_test.py'),
                                *args],capture_output=True,text=True,timeout=30)
            self.assertNotEqual(p.returncode,0)
            self.assertIn('disconnected motor required',p.stderr)

    def test_actual_and_encoder_acceptance_still_required(self):
        self.assertIsNone(board.previous.acceptance_failure(dict(
            encoder_priority_verified=True,timing=dict(preempt_max_us=0),
            encoder_events=dict(deferred_service_count=3,rx_event_count=2,
                                period_count=1,tx_error_count=0))))
        self.assertIsNotNone(board.previous.acceptance_failure(dict(
            encoder_priority_verified=False,timing=dict(preempt_max_us=0),encoder_events={})))

    def test_restore_bootloader_owner_stays_strict_and_restores_gate(self):
        original = board.base.tx.prior.off_gate
        def exercise(*unused):
            commands = board.base.tx.prior.off_gate(0x08008000)
            self.assertEqual(commands, original(0))
        row = {}
        with patch.object(board.base.tx,'read_receipt',return_value={'snapshot_vtor':0}), \
             patch.object(board,'_restore',side_effect=exercise):
            board.restore(row,'test',b'',Path('unused.json'))
        self.assertTrue(row['restore_from_stopped_bootloader'])
        self.assertIs(board.base.tx.prior.off_gate, original)
        with patch.object(board.base.tx,'read_receipt',return_value={'snapshot_vtor':0x08040000}), \
             patch.object(board,'_restore') as call:
            with self.assertRaises(ValueError): board.restore({},'test',b'',Path('unused.json'))
            call.assert_not_called()


if __name__ == '__main__': unittest.main()
