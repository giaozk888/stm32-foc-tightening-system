from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
import current_pi_fsm_board as selected


class CurrentPiFsmBoardTests(unittest.TestCase):
    def test_pinned_image_original_b_and_files_only(self):
        with patch.object(selected.base.hw,'debug',side_effect=AssertionError('device')):
            self.assertEqual(selected.main([]),0)
        self.assertEqual(len(selected.image()),217428)
        self.assertEqual(selected.base.FRICTION_A,.105)

    def test_missing_physical_conditions_no_devices(self):
        with patch.object(selected.base.hw,'debug') as debug,patch.object(selected.base.support.support,'open_port') as port:
            for args in (['--stage-off'],['--execute-powered','unused.json']):
                with self.assertRaises(SystemExit):selected.main(args)
            debug.assert_not_called();port.assert_not_called()

    def test_reuses_original_single_start_and_off_closure(self):
        import inspect
        src=inspect.getsource(selected.base.motion)
        self.assertIn("row['start_attempts']=1",src)
        self.assertIn("No second START",src)
        self.assertIn("Protection fault; no retry",src)
        self.assertIn("'ANALOG SAFE'",src)
        self.assertIn("CONTACT on confirmed no-load fixture",src)
        execute=inspect.getsource(selected.base.execute)
        self.assertIn('wait_timing',execute)
        self.assertIn('capture_stopped',execute)


if __name__=='__main__':unittest.main()
