"""Offline deployment gates; never open a probe or serial port."""
import importlib.util
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
import protected_compact_closed_loop_stage as stage

class CompactMotorStageTests(unittest.TestCase):
    def test_exact_a_image_and_scoped_authorization(self):
        self.assertEqual(len(stage.pinned_image()),207972)
        for flags in ([],['--drive-12v-off'],['--drive-12v-off','--allow-inactive-stage']):
            with patch.object(sys,'argv',['stage',*flags]),patch.object(stage,'Board') as board:
                with self.assertRaises(SystemExit): stage.main()
                board.assert_not_called()

    def test_wrong_image_refused(self):
        bad=stage.IMAGE.read_bytes()[:-1]+b'\x00'
        with patch.object(Path,'read_bytes',return_value=bad):
            with self.assertRaises(RuntimeError): stage.pinned_image()

    def test_other_receipt_and_metadata_cannot_select_baseline(self):
        with self.assertRaises(RuntimeError):
            stage.verified_baseline(b'\x00'*0x80000,ROOT/'not-the-baseline.json')
        # Path check fails before accessing any private capture or board.

if __name__=='__main__': unittest.main()
