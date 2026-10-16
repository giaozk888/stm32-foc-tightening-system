import sys
from pathlib import Path
import unittest
from unittest.mock import patch
import protected_irq_optimized_stage as profile
import protected_timing_fix_stage as previous

class OptimizedStageTests(unittest.TestCase):
    def test_exact_new_image_and_old_pin_preserved(self):
        self.assertEqual(len(profile.pinned_image()),205592)
        self.assertEqual(len(previous.pinned_image()),205200)
        self.assertNotEqual(profile.SHA,previous.SHA)
    def test_baseline_chain_retains_its_historical_profile(self):
        source=Path(profile.__file__).read_text('utf-8')
        self.assertIn('source_profile=previous',source)
        self.assertIn('(2,0,0,477)',source)
        self.assertIn('before!=failed',source)
        self.assertIn("actual[0x78000:]!=before[0x78000:]",source)
        self.assertIn('allow_reset=False',source)
        self.assertNotIn("query('FW END'",source)
        self.assertNotIn("query('MOTOR TEST SPEED'",source)
    def test_board_rejects_writes_and_reset_before_hardware(self):
        board=profile.Board({'steps':[]},'test')
        for operation in ('-w','-d','-e','-rst','-ob'):
            with self.subTest(operation=operation),self.assertRaises(ValueError): board.cli(operation)
    def test_mismatched_image_rejected(self):
        with patch.object(profile,'SHA','0'*64),self.assertRaises(RuntimeError): profile.pinned_image()

if __name__=='__main__': unittest.main()
