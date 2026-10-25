from pathlib import Path
import hashlib
import json
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import dob_short_low_board as board


class ShortLowBoardTests(unittest.TestCase):
    def test_reviewed_candidate_and_original_control_sources(self):
        self.assertEqual(len(board.image()), 228592)
        manifest = json.loads((ROOT / 'simulation/dob_simulink/low_recovery_results/20261024_171018/manifest.json').read_text())
        for source in manifest['sources']:
            if source['path'].endswith('main.c'):
                self.assertEqual(hashlib.sha256(Path(source['path']).read_bytes()).hexdigest(), source['sha256'])

    def test_physical_gates_precede_configuration(self):
        for args in (['--stage-off'], ['--execute-powered', 'missing'], ['--restore-b-drive-off', 'missing']):
            with patch.object(board, 'configure') as configure:
                with self.assertRaises(SystemExit):
                    board.main(args)
                configure.assert_not_called()

    def test_configuration_pins_the_latest_real_stopped_baseline(self):
        board.configure(board.ROOT_RESTORE)
        receipt = json.loads(board.ROOT_RESTORE.read_text())
        self.assertEqual(board.base.BASE.resolve(), Path(receipt['final_capture']).resolve())
        self.assertEqual(list(board.base.EXPECT_META), receipt['metadata'])
        self.assertEqual(board.base.EXPECT_META[5], 1238)

    def test_repeat_uses_successful_latest_restore_without_rebuilding(self):
        receipt_path = ROOT / 'tmp/dob-short-low-restore-1792836112900893600.json'
        receipt = json.loads(receipt_path.read_text())
        # Each real invocation is a fresh process; legacy wrappers mutate module bindings.
        source = "import sys,json;sys.path.insert(0,'tools');import dob_short_low_board as b;from pathlib import Path;b.configure(Path(sys.argv[1]));print(json.dumps([str(b.base.BASE),list(b.base.EXPECT_META)]))"
        completed = subprocess.run([sys.executable, '-c', source, str(receipt_path)], cwd=ROOT,
                                   capture_output=True, text=True, check=True)
        capture, metadata = json.loads(completed.stdout.strip())
        self.assertEqual(Path(capture).resolve(), Path(receipt['final_capture']).resolve())
        self.assertEqual(metadata, receipt['metadata'])
        self.assertEqual(metadata[5], 1242)

    def test_powered_source_baseline_cannot_be_overridden(self):
        with patch.object(board, 'configure') as configure:
            with self.assertRaises(SystemExit):
                board.main(['--execute-powered', 'missing', '--baseline-restore', 'other',
                            '--operator-present-drive-on-no-alarm-05a', '--dynamic-brake-immediately-releasable'])
            configure.assert_not_called()

    def test_decode_uses_matching_elf_and_counters(self):
        ram = bytearray(200)
        struct.pack_into('<4f14I7f', ram, 0, *([0.] * 4 + [0] * 14 + [0.] * 7))
        struct.pack_into('<8I', ram, 128, 10, 0, 0, 0, 0, 0, 0, 0)
        struct.pack_into('<I', ram, 160, 3)
        symbols = {'dob_low_recovery': (0x20000000, 100),
                   'dob_saturation_audit': (0x20000080, 32), 'dob_warmup_tau': (0x200000A0, 4)}
        with tempfile.TemporaryDirectory(dir=ROOT / 'tmp') as directory:
            path = Path(directory) / 'ram.bin'
            path.write_bytes(ram)
            row = dict(ram_capture=str(path), trend_capture={'header': {'observations': 10}}, start_attempts=0)
            with patch.object(board.continuous, 'decode'), patch.object(board.base, 'symbols', return_value=symbols):
                board.decode(row)
                self.assertEqual(row['short_low_recovery']['fast'], 0)
                struct.pack_into('<I', ram, 28, 99)  # Invalid mode, never a successful decode.
                path.write_bytes(ram)
                with self.assertRaises(ValueError):
                    board.decode(row)

    def test_full_replay_parity_evidence(self):
        review = json.loads((ROOT / 'tmp/dob-short-low-build-review.json').read_text())
        parity = review['original_offline_parity']
        self.assertEqual(parity['trials'], 140)
        self.assertEqual(parity['epochs'], 140 * 7001)
        self.assertTrue(parity['bitwise_observer_feedback_equal'])
        self.assertTrue(parity['valid_sample_counter_closure'])
        for name, expected in review['sources'].items():
            self.assertEqual(hashlib.sha256((ROOT / name).read_bytes()).hexdigest(), expected)


if __name__ == '__main__':
    unittest.main()
