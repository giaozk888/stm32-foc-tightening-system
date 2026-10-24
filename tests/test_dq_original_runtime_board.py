import sys
from pathlib import Path
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
import dq_original_runtime_board as run


class RuntimeBoardTests(unittest.TestCase):
    def test_default_no_devices_validates_exact_B920_and_old_runtime(self):
        with patch.object(run.original.base.hw,'debug',side_effect=AssertionError('device')):
            self.assertEqual(run.main([]),0)
            self.assertEqual(run.original.base.EXPECT_META[2:6],(2,0,0,920))
            self.assertEqual(len(run.original.image()),219300)
            self.assertIs(run.original.base.motion,run.original.motion)
            self.assertIs(run.original.base.TokenRecordedBoard,run.original.ORIGINAL_BOARD)

    def test_no_physical_state_no_hardware(self):
        with patch.object(run.original.base.hw,'debug') as debug:
            for args in (['--stage-off'],['--execute-powered','unused'],['--restore-b-drive-off','unused']):
                with self.assertRaises(SystemExit):run.main(args)
            debug.assert_not_called()

    def test_false_B920_identity_fails_before_flash(self):
        with patch.object(run,'ROOT_SHA','0'*64),patch.object(run.original.base.hw,'debug') as debug:
            with self.assertRaises(ValueError):run.configure(run.ROOT_RECEIPT)
            debug.assert_not_called()


if __name__=='__main__':unittest.main()
