"""No device IO: terminal-fix image/B832 pins, unchanged one-shot closure."""
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
import motor_ident_encoder_terminal_board as selected
import test_motor_identification_board as old


class EncoderTerminalBoardTests(unittest.TestCase):
    def test_pins_and_default_no_device(self):
        self.assertEqual(len(selected.image()),214764)
        with patch.dict(selected.base.__dict__,{}):
            selected.configure()
            self.assertEqual(selected.base.EXPECT_META[2:6],(2,0,0,832))
            self.assertEqual(selected.base.old.zero.digest(selected.base.baseline()),selected.BASE_SHA)
        p=subprocess.run([sys.executable,str(ROOT/'tools/motor_ident_encoder_terminal_board.py')],
                         capture_output=True,text=True,timeout=15)
        self.assertEqual(p.returncode,0,p.stdout+p.stderr)
        self.assertIn('B832, no devices',p.stdout)

    def test_still_only_one_rs50_then_closes(self):
        class Board(old.FakeBoard):
            def command(self,cmd,*args):
                if cmd=='MOTOR TEST IDENT TIME POLICY':
                    self.calls.append(cmd)
                    return 'OK RS_DT_MAX=100 L_DT_MAX=55 DT_MIN=45 GAP_DT_PER_SEQ_MAX=55'
                return super().command(cmd,*args)
        b=Board();row={'postflight':{}}
        with old.IdentBoardTests().motion_patches(),patch.object(selected.run,'EXTRA_READOUT',None):
            selected.previous.previous.motion(b,row)
        self.assertEqual(b.calls.count(selected.run.COMMAND),1)
        self.assertNotIn('START',b.calls)
        self.assertIn('MOTOR TEST STOP',b.calls);self.assertIn('ANALOG SAFE',b.calls)

    def test_encoder_evidence_retained_on_quality_failure(self):
        row={}
        with patch.object(selected.encoder_report,'decode_saved',return_value={'test_saved':True}),\
             patch.object(selected.previous,'extra_decode',side_effect=ValueError('insufficient')):
            with self.assertRaises(ValueError):selected.extra_decode(row,b'',0)
        self.assertTrue(row['encoder_terminal_saved']['test_saved'])


if __name__=='__main__':unittest.main()
