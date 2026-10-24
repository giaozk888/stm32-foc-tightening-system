"""No hardware: one-axis transport and provisional-Rs result semantics."""
import copy
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch
from test_motor_identification import l_run
from test_motor_identification_board import IdentBoardTests,FakeBoard
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
import motor_ident_l_axis_board as l


class LAxisTests(unittest.TestCase):
    def test_files_only_current_baseline_both_axis(self):
        for axis in ('LD','LQ'):
            p=subprocess.run([sys.executable,str(ROOT/'tools/motor_ident_l_axis_board.py'),
                '--axis',axis],text=True,capture_output=True,timeout=20)
            self.assertEqual(p.returncode,0,p.stdout+p.stderr)
            self.assertIn('no devices',p.stdout)

    def test_provisional_rs_never_becomes_formal_or_generates_pi(self):
        for axis in ('LD','LQ'):
            r=l_run(axis)
            out=l.estimate(r)
            self.assertFalse(out['rs_qualified'])
            self.assertTrue(out['conditional_on_assumed_rs'])
            self.assertFalse(out['automatic_pi_write'])
            self.assertIsNone(out['pi_suggestion'])
            # No fabricated board latch proof, even with operator-chosen Rs.
            r['latch_evidence']={'verified':False}
            out=l.estimate(r)
            self.assertIsNone(out[axis.lower()])
            self.assertIn('TIMING_UNQUALIFIED',out['quality_error'])

    def test_single_ld_lq_command_and_unknown_ack_no_retry(self):
        helper=IdentBoardTests()
        for axis in ('LD','LQ'):
            cmd='MOTOR TEST IDENT %s RS_VALIDATED LOCKED CONFIRM'%axis
            for refuse in (False,True):
                board=FakeBoard(refuse)
                with patch.object(l.run,'COMMAND',cmd),patch.object(l.run,'EXTRA_READOUT',None),helper.motion_patches():
                    row={'postflight':{}}
                    if refuse:
                        with self.assertRaises(TimeoutError):l.ORIGINAL_MOTION(board,row,ident_mode=axis)
                    else:l.ORIGINAL_MOTION(board,row,ident_mode=axis)
                self.assertEqual(board.calls.count(cmd),1)
                self.assertNotIn('START',board.calls)
                self.assertIn('ANALOG SAFE',board.calls)
                self.assertFalse(any('RS 50 LOCKED' in x for x in board.calls))

    def test_wrong_mode_and_missing_conditions_never_open_devices(self):
        with patch.object(l.run,'COMMAND','MOTOR TEST IDENT RS 50 LOCKED CONFIRM'):
            board=FakeBoard()
            with self.assertRaises(ValueError):l.ORIGINAL_MOTION(board,{},ident_mode='LD')
            self.assertFalse(board.calls)
        with patch.object(l.base.hw,'debug') as d,patch.object(l.base.support.support,'open_port') as p:
            with self.assertRaises(ValueError):l.run.execute({},'unused',ROOT/'tmp/unused.json',b'')
            d.assert_not_called();p.assert_not_called()

    def test_resume_rejects_any_potential_prior_excitation(self):
        with patch.object(l,'AXIS','LD'),patch.object(l.base,'baseline') as baseline:
            with patch.object(l.json,'loads',return_value=dict(mode='run',test={'mode':'LD'},
                image_sha256=l.SHA,elf_sha256=l.ELF_SHA,excitation_attempts=1,
                final_cpu_halted=True,final_outputs_off=True,all_app_private_unchanged=True)):
                with patch.object(Path,'read_text',return_value='{}'):
                    with self.assertRaises(ValueError):l.unused_source(l.TMP/'not-run.json',b'')
            baseline.assert_not_called()


if __name__=='__main__':unittest.main()
