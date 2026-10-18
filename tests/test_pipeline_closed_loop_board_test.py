"""Host-only gates for the protected candidate stager; no device operations."""
import copy
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
import pipeline_closed_loop_board_test as board


class CandidateBoardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = board.IMAGE.read_bytes()
        cls.elf = board.ELF.read_bytes()
        cls.receipt = json.loads((board.ROOT/'tests/foc_adaptive_build/pipeline_closed_loop_evidence/receipt.json').read_text())

    def test_exact_offline_candidate(self):
        board.verify_build(self.data, self.elf, self.receipt)

    def test_changed_image_or_elf_rejected(self):
        for data, elf in ((self.data[:-1], self.elf), (self.data, self.elf[:-1])):
            with self.assertRaises(ValueError):
                board.verify_build(data, elf, self.receipt)

    def test_wrong_or_failed_receipt_rejected(self):
        for key, value in (('hardware_access', True), ('test_count', 167),
                           ('motor_started', True), ('boot_selection_changed', True)):
            receipt = copy.deepcopy(self.receipt)
            receipt[key] = value
            with self.assertRaises(ValueError):
                board.verify_build(self.data, self.elf, receipt)

    def test_default_no_devices(self):
        with patch.object(sys, 'argv', ['board']), patch.object(board.tx, 'baseline') as baseline, \
                patch.object(board.tx, 'stage') as stage:
            self.assertEqual(board.main(), 0)
            baseline.assert_not_called()
            stage.assert_not_called()

    def test_power_confirmation_required_before_image_or_hardware(self):
        with patch.object(sys, 'argv', ['board', '--stage-inactive-a']), \
                patch.object(board, 'image') as image, patch.object(board.tx, 'stage') as stage:
            with self.assertRaises(SystemExit):
                board.main()
            image.assert_not_called()
            stage.assert_not_called()

    def test_stage_module_has_no_trial_or_start_mode(self):
        with patch.object(sys, 'argv', ['board', '--trial-from-stage', 'anything']), \
                patch.object(board, 'image') as image:
            with self.assertRaises(SystemExit):
                board.main()
            image.assert_not_called()


if __name__ == '__main__':
    unittest.main()
