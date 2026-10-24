"""No hardware: exact unchanged A/B852, only one Rs100 command."""
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
import motor_ident_rs100_point_board as selected
import test_motor_identification_board as old


class Rs100PointBoardTests(unittest.TestCase):
    def test_pins_and_offline_only(self):
        self.assertEqual(len(selected.image()),215132)
        with patch.dict(selected.base.__dict__,{}):
            selected.configure();self.assertEqual(selected.base.EXPECT_META[2:6],(2,0,0,852))
        p=subprocess.run([sys.executable,str(ROOT/'tools/motor_ident_rs100_point_board.py')],
                         capture_output=True,text=True,timeout=15)
        self.assertEqual(p.returncode,0,p.stdout+p.stderr)
        self.assertIn('RS100-only A and B852, no devices',p.stdout)

    def test_one_point_no_retry_no_other_currents(self):
        b=old.FakeBoard();row={'postflight':{}}
        with patch.dict(selected.run.__dict__,{'RS_MA':100,'COMMAND':'MOTOR TEST IDENT RS 100 LOCKED CONFIRM',
                                              'EXTRA_READOUT':None}),old.IdentBoardTests().motion_patches():
            selected.run.motion(b,row)
        self.assertEqual(b.calls.count('MOTOR TEST IDENT RS 100 LOCKED CONFIRM'),1)
        self.assertFalse(any('RS 50' in x or 'RS 75' in x or 'IDENT LD' in x or 'IDENT LQ' in x for x in b.calls))
        self.assertIn('ANALOG SAFE',b.calls)

    def test_wrong_reference_rejected(self):
        row={'ident_ram':{'current_a':.075},'acquisition_pass':True}
        with patch.object(selected.previous.previous,'extra_decode'):
            with self.assertRaises(ValueError):selected.extra_decode(row,b'',0)
        self.assertFalse(row['acquisition_pass'])


if __name__=='__main__':unittest.main()
