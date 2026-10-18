"""File-only and mocked no-motion gates for the trace timing adapter."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
import current_fault_trace_board_test as board


class TraceBoardTests(unittest.TestCase):
    def test_exact_build_and_baseline(self):
        data = board.image()
        self.assertEqual(len(data), board.SIZE)
        with patch.multiple(board.candidate.tx, BASE_RECEIPT=board.BASE_RECEIPT,
                BASE_SHA=board.BASE_SHA, BASE_META=board.BASE_META, B_SHA=board.B_SHA):
            _, raw = board.candidate.tx.baseline()
            self.assertEqual(board.latest_meta(raw)[2:6], (2,0,0,619))

    def test_changed_image_rejected(self):
        with patch.object(Path, 'read_bytes', return_value=b'changed'):
            with self.assertRaises(ValueError):
                board.image()

    def test_default_no_hardware(self):
        with patch.object(sys,'argv',['board']), patch.object(board,'configure') as config:
            self.assertEqual(board.main(), 0)
            config.assert_not_called()

    def test_physical_gate_before_files_or_hardware(self):
        for args in (['--stage-inactive-a'],['--trial-from-stage','x'],['--restore-from-trial','x']):
            with patch.object(sys,'argv',['board',*args]), patch.object(board,'image') as image:
                with self.assertRaises(SystemExit):
                    board.main()
                image.assert_not_called()

    def test_no_start_option(self):
        with patch.object(sys,'argv',['board','--allow-one-original-start']), \
                patch.object(board,'image') as image:
            with self.assertRaises(SystemExit):
                board.main()
            image.assert_not_called()

    def test_trial_always_motion_false(self):
        def run(row, *args, **kwargs):
            self.assertIs(kwargs['motion'], False)
            row['pass_'] = True
        with tempfile.TemporaryDirectory() as folder, \
                patch.object(board,'OUTPUT',Path(folder)), \
                patch.object(sys,'argv',['board','--trial-from-stage','x',
                    '--drive-12v-on-no-alarm-motor-disconnected']), \
                patch.object(board,'configure'), patch.object(board,'decode'), \
                patch.object(board.trial,'load_stage'), \
                patch.object(board.trial,'run_trial',side_effect=run) as trial:
            self.assertEqual(board.main(), 0)
            trial.assert_called_once()
            receipt = json.loads(next(Path(folder).glob('*.json')).read_text('utf-8'))
            self.assertEqual(receipt['original_start_runner_invocations'], 0)
            self.assertFalse(receipt['image_compile_time_hard_off'])


if __name__ == '__main__':
    unittest.main()
