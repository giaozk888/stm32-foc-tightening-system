"""No devices: exact new image and fault-window classification regression."""
from copy import deepcopy
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
import current_invalid_rolling_trace_board_test as board


def fixture():
    frames = []
    for i in range(16):
        frames.append(dict(seq=100+i, raw_u=1600,raw_v=1600,
            reference_u_before=1500,reference_v_before=1500,
            candidate_u_before=1700,candidate_v_before=1700,
            d_old=100,d_candidate=100,unresolved_consecutive_before=0,
            discriminator_executed=1,decision_path=1,discriminator_result=1,
            protection_fault=0,protection_reason=0))
    for i,r in enumerate(frames[-3:]):
        r.update(unresolved_consecutive_before=i,decision_path=3,discriminator_result=0)
    frames[-1].update(discriminator_result=-1,protection_fault=1,protection_reason=11)
    return (dict(magic=0x43545232,frozen=1,freeze_reason=1,fault_seq=115), frames,
        dict(valid=1,domain=2,fault_reason=11,adc_sample_count=115))


class RollingBoardTests(unittest.TestCase):
    def test_exact_image_file_only(self):
        self.assertEqual(len(board.image()),229364)

    def test_first_fault_window(self):
        result=board.acquisition(*fixture())
        self.assertTrue(result['captured'])
        self.assertFalse(result['control_pass'])
        self.assertEqual(result['unresolved_seqs'],[113,114,115])

    def test_not_frozen_is_not_reproduced(self):
        h,r,f=fixture(); h['frozen']=0
        self.assertFalse(board.acquisition(h,r,f)['captured'])

    def test_mismatched_context_rejected(self):
        for key,value in (('adc_sample_count',114),('fault_reason',6),('valid',0)):
            h,r,f=fixture(); f[key]=value
            with self.assertRaises(ValueError): board.acquisition(h,r,f)

    def test_missing_unresolved_or_before_operands_rejected(self):
        for key,value in (('unresolved_consecutive_before',9),('candidate_u_before',2000)):
            h,r,f=fixture(); r[-2][key]=value
            with self.assertRaises(ValueError): board.acquisition(h,r,f)

    def test_wrong_schema_or_incomplete_window_rejected(self):
        h,r,f=fixture(); h['magic']=0x43545231
        with self.assertRaises(ValueError): board.acquisition(h,r,f)
        h,r,f=fixture()
        with self.assertRaises(ValueError): board.acquisition(h,r[1:],f)

    def test_default_no_hardware_and_bindings_restored(self):
        old=board.previous.IMAGE
        with patch.object(sys,'argv',['board']),patch.object(board.previous,'configure') as config:
            self.assertEqual(board.main(),0)
            config.assert_not_called()
        self.assertEqual(board.previous.IMAGE,old)

    def test_physical_gates_and_no_start_option(self):
        for args in (['--stage-inactive-a'],['--trial-from-stage','x'],
                ['--restore-from-trial','x'],['--allow-one-original-start']):
            with patch.object(sys,'argv',['board',*args]),patch.object(board,'image') as image:
                with self.assertRaises(SystemExit): board.main()
                image.assert_not_called()


if __name__ == '__main__':
    unittest.main()
