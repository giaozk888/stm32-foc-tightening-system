import copy
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'tools'))
import dob_load_speed_contact_board as board


class ContactBoardTests(unittest.TestCase):
    def test_exact_v2_image_and_abi_and_safety_flags(self):
        self.assertEqual(len(board.image()),228712)
        self.assertEqual(board.base.symbols(board.ELF)['dob_load_speed'][1],68)

    def test_physical_confirmation_gates_precede_configuration(self):
        for args in (['--stage-off'],['--restore-b-drive-off','absent'],['--execute-powered','absent']):
            with patch.object(board,'configure') as cfg:
                with self.assertRaises(SystemExit):board.main(args)
                cfg.assert_not_called()

    def test_v1_or_incomplete_staging_plan_cannot_execute(self):
        plan=dict(window_ms=75,warmup_tau_requested=3,load_speed_candidate=True,contact_hold=True,load_speed_trace_abi=2)
        board.validate_plan(plan)
        for key in ('contact_hold','load_speed_trace_abi','window_ms','warmup_tau_requested'):
            invalid=copy.deepcopy(plan);invalid.pop(key)
            with self.assertRaises(ValueError):board.validate_plan(invalid)

    def test_default_validates_latest_halted_b_without_devices(self):
        with patch.object(board.base.hw,'debug') as debug:
            self.assertEqual(board.main([]),0);debug.assert_not_called()
        self.assertEqual(board.base.EXPECT_META[5],1254)
        self.assertEqual(board.base.EXPECT_META[8:10],(227964,627317606))


if __name__=='__main__':unittest.main()
