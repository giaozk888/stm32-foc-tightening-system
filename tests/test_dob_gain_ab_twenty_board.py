import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
import dob_gain_ab_twenty_board as b

class GainAbBoardTests(unittest.TestCase):
    def test_exact_candidate_and_baseline_files_only(self):
        self.assertEqual(len(b.image()),224228)
        self.assertTrue(json.loads(b.ROOT_RESTORE.read_text())['b_application_not_run'])
    def test_missing_confirmation_never_configures_or_contacts_board(self):
        for args in [['--stage-off'],['--execute-twenty','missing'],['--restore-b-drive-off','missing']]:
            with patch.object(b,'configure') as configure:
                with self.assertRaises(SystemExit):b.main(args)
                configure.assert_not_called()
    def test_exact_twenty_alternating_and_no_retry(self):
        parent={'baseline_restore_receipt':'baseline'};gains=[]
        def run(row,name,current,data):
            gains.append(row['dob_gain_requested'])
            row.update(pass_=True,actual_gain_ram=row['dob_gain_requested'],final_cpu_halted=True)
        with patch.object(b,'image',return_value=b'A'),patch.object(b.raw,'run_one',side_effect=run),\
             patch.object(b.base.old.prior,'checkpoint'):
            b.execute_twenty(Path('stage'),parent)
        self.assertEqual(gains,[.25,.5]*10)
        self.assertEqual([parent['comparison']['groups'][str(g)]['runs'] for g in [.25,.5]],[10,10])
        parent={'baseline_restore_receipt':'baseline'}
        with patch.object(b,'image',return_value=b'A'),patch.object(b.raw,'run_one',side_effect=RuntimeError('real protection')) as run,\
             patch.object(b.base.old.prior,'checkpoint'):
            with self.assertRaisesRegex(RuntimeError,'real protection'):b.execute_twenty(Path('stage'),parent)
            self.assertEqual(run.call_count,1)
    def test_gain_mismatch_stops_no_next_run(self):
        def run(row,*args):row.update(pass_=True,actual_gain_ram=.5,final_cpu_halted=True)
        with patch.object(b,'image',return_value=b'A'),patch.object(b.raw,'run_one',side_effect=run) as run,\
             patch.object(b.base.old.prior,'checkpoint'):
            with self.assertRaisesRegex(ValueError,'gain evidence'):b.execute_twenty(Path('stage'),{'baseline_restore_receipt':'baseline'})
            self.assertEqual(run.call_count,1)
    def test_only_guarded_selection_and_exact_readback_before_original_start_path(self):
        class Board:
            def __init__(self,wrong=False):self.commands=[];self.wrong=wrong
            def command(self,cmd):
                self.commands.append(cmd)
                if cmd.endswith('GAIN 500000'):return 'OK DOBGAIN GAIN_PPM=500000 ON=0 RAM_ONLY=1'
                conf=dict(b.normal.FB_CONFIG,GAIN_PPM='250000' if cmd.endswith('CFG') or self.wrong else '500000',ON='0' if cmd.endswith('CFG') else '1')
                return 'OK DOBFB '+' '.join(k+'='+v for k,v in conf.items())
        row={'dob_gain_requested':.5,'postflight':{}};board=Board()
        with patch.object(b.raw,'motion') as motion:b.motion(board,row);motion.assert_called_once()
        self.assertEqual(board.commands,['MOTOR TEST MECH DOB FB CFG','MOTOR TEST MECH DOB FB GAIN 500000','MOTOR TEST MECH DOB FB ON',
                                         'MOTOR TEST MECH DOB STATS','MOTOR TEST MECH DOB ADMIT GAPS'])
        with patch.object(b.raw,'motion') as motion:
            with self.assertRaises(RuntimeError):b.motion(Board(True),row)
            motion.assert_not_called()

if __name__=='__main__':unittest.main()
