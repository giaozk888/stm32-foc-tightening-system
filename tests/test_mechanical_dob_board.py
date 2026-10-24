import json
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'tools'))
import mechanical_dob_board as board


class DobBoardTests(unittest.TestCase):
    def test_files_only_default_exact_new_image_and_actual_old_b_restore(self):
        p = subprocess.run([sys.executable, str(ROOT/'tools/mechanical_dob_board.py')],
                           cwd=ROOT, text=True, capture_output=True)
        self.assertEqual(p.returncode, 0, p.stdout+p.stderr)
        self.assertIn('1 mechanical points; no devices', p.stdout)
        self.assertEqual(len(board.image()), board.SIZE)
        r = json.loads(board.ROOT_RESTORE.read_text())
        self.assertTrue(r['pass_'] and r['b_application_not_run'])
        self.assertEqual(r['image_sha256'], board.previous.SHA)
        self.assertNotEqual(r['image_sha256'], board.SHA)

    def test_physical_gates_before_setup_single_point_and_frozen_thresholds(self):
        low = board.low
        with patch.multiple(low, setup=low.setup, POINTS=low.POINTS, TRIP_RPM=low.TRIP_RPM,
                            TRAVEL_DEG=low.TRAVEL_DEG, CLOSURE_SECONDS=low.CLOSURE_SECONDS,
                            LIMITS_QUERY=low.LIMITS_QUERY, LIMITS_EXTRA=low.LIMITS_EXTRA), \
                patch.object(board, 'ORIGINAL_SETUP') as setup:
            for args in (['--prepare-off'], ['--execute-positive', 'missing'],
                         ['--restore-b-drive-off', 'missing']):
                with self.assertRaises(SystemExit):
                    board.main(args)
            setup.assert_not_called()
            with patch.object(low, 'main', return_value=0):
                board.main([])
            self.assertEqual(low.POINTS, (600,))
            self.assertEqual(low.TRIP_RPM, 1000)
            self.assertEqual(low.TRAVEL_DEG, 30000)
            self.assertEqual(low.CLOSURE_SECONDS, 11.)

    def new(self):
        b = object.__new__(board.DobBoard)
        b.record = {}
        return b

    def replies(self):
        return ['1 OK MECH DOB_SHADOW=1 SIGNS=POS,NEG GRID_RPM=600 DOB_CONTROL=0',
                '2 OK DOB MODEL '+' '.join(k+'='+v for k,v in board.MODEL.items()),
                '3 OK DOB SHADOW=1 FEEDBACK=0 LIVE=0 VALID=0',
                '4 OK MECH QUEUED RPM=600']

    def test_only_one_run_after_exact_dob_model_and_existing_readiness_owner(self):
        run = 'MOTOR TEST MECH RUN POS 600'
        with patch.object(board.ORIGINAL_BOARD, 'command', side_effect=self.replies()) as send:
            b = self.new()
            self.assertIn('QUEUED', b.command(run))
            self.assertEqual([c.args[0] for c in send.call_args_list],
                ['MOTOR TEST MECH DIRECTION', 'MOTOR TEST MECH DOB MODEL', 'MOTOR TEST MECH DOB', run])
            self.assertTrue(b.dob_started)
            self.assertEqual(b.record['dob_model_before_start'], board.MODEL)
        for command in ('START', 'MOTOR TEST MECH RUN NEG 600', 'MOTOR TEST MECH RUN POS 700'):
            if command == 'START':
                # The wrapper never emits START; compiled diagnostic rejects it.
                continue
            with patch.object(board.ORIGINAL_BOARD, 'command') as send:
                with self.assertRaises(ValueError):
                    self.new().command(command)
                send.assert_not_called()

    def test_wrong_identity_model_feedback_or_missing_ack_never_retries(self):
        run = 'MOTOR TEST MECH RUN POS 600'
        for index, changed in ((0, '1 OK MECH SIGN=-1'),
                               (1, self.replies()[1].replace('IC_UA=119451', 'IC_UA=120735')),
                               (2, '3 OK DOB SHADOW=1 FEEDBACK=1 LIVE=0 VALID=0')):
            replies = self.replies()
            replies[index] = changed
            with patch.object(board.ORIGINAL_BOARD, 'command', side_effect=replies) as send:
                with self.assertRaises(RuntimeError):
                    self.new().command(run)
                self.assertFalse(any(c.args[0] == run for c in send.call_args_list))
        with patch.object(board.ORIGINAL_BOARD, 'command', side_effect=self.replies()[:3]+[TimeoutError('ACK')]) as send:
            with self.assertRaises(TimeoutError):
                self.new().command(run)
            self.assertEqual(sum(c.args[0] == run for c in send.call_args_list), 1)

    def test_sparse_readonly_views_never_repair_rearm_or_enable_feedback(self):
        replies = ['1 OK MECH RPM=600 ACTIVE=1 DONE=0',
                   '2 OK DOB SHADOW=1 FEEDBACK=0 LIVE=1 VALID=1 US=1000 D_UA=2000',
                   '3 OK DOB ADC SHADOW=1 FEEDBACK=0 LIVE=1 VALID=1 US=1000 SEQ=20',
                   '4 OK DOB STATS SHADOW=1 FEEDBACK=0 LIVE=1 GOOD=100 N=500']
        with patch.object(board.ORIGINAL_BOARD, 'command', side_effect=replies) as send:
            b = self.new()
            b.dob_started, b.dob_next = True, 0.
            b.command('MOTOR TEST MECH STATUS')
            self.assertEqual([c.args[0] for c in send.call_args_list],
                ['MOTOR TEST MECH STATUS', 'MOTOR TEST MECH DOB', 'MOTOR TEST MECH DOB ADC',
                 'MOTOR TEST MECH DOB STATS'])
            self.assertEqual(len(b.record['dob_samples']), 1)
            self.assertEqual(b.record['dob_samples'][0]['frame']['values']['VALID'], '1')
        with patch.object(board.ORIGINAL_BOARD, 'command', return_value=replies[0]) as send:
            b.command('MOTOR TEST MECH STATUS')
            self.assertEqual(send.call_count, 1)

    def test_postflight_same_session_decode_after_original_safety_checks_and_fault_finally(self):
        row = dict(receipt_path='receipt', ram_capture='ram')
        captured = dict(meta=dict(valid_samples=100, observations=500, rejected_samples=3,
                                 disturbance_abs_peak=.02, max_compute_us=8), positive_mean_a=.005)
        with patch.object(board, 'ORIGINAL_RUN') as run, \
                patch.object(board.dob_report, 'decode', return_value=captured) as decode, \
                patch.object(board.previous.previous.previous, 'decode_trace', return_value={}), \
                patch.object(board.previous.previous, 'decode_readiness', return_value={}):
            board.run_point(row, 'name', 'source', 'before', 'data', 600, True)
            run.assert_called_once()
            decode.assert_called_once_with(Path('receipt'), board.ELF)
            self.assertEqual(row['dob_summary']['valid_fraction'], .2)
            self.assertFalse(row['dob_summary']['feedback_enabled'])
        with patch.object(board, 'ORIGINAL_RUN', side_effect=RuntimeError('fault')), \
                patch.object(board.dob_report, 'decode') as decode, \
                patch.object(board.previous.previous.previous, 'decode_trace', return_value={}) as trace, \
                patch.object(board.previous.previous, 'decode_readiness', return_value={}):
            with self.assertRaisesRegex(RuntimeError, 'fault'):
                board.run_point(row)
            decode.assert_not_called()
            trace.assert_called_once()


if __name__ == '__main__':
    unittest.main()
