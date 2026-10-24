import json
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
import dob_feedback_gainhalf_board as board

class GainHalfBoardTests(unittest.TestCase):
    def test_files_only_half_gain_and_actual_prior_gain1_b1095(self):
        p=subprocess.run([sys.executable,str(ROOT/'tools/dob_feedback_gainhalf_board.py')],cwd=ROOT,text=True,capture_output=True)
        self.assertEqual(p.returncode,0,p.stdout+p.stderr);self.assertIn('no devices',p.stdout)
        board.image();r=json.loads(board.ROOT_RESTORE.read_text())
        self.assertEqual(r['metadata'][5],1095);self.assertTrue(r['pass_'] and r['b_application_not_run'])
        self.assertEqual(r['image_sha256'],board.previous.SHA)
        self.assertEqual(board.FB_CONFIG['GAIN_PPM'],'500000')
        self.assertEqual(board.FB_CONFIG['CAP_UA'],'25000')

    def test_fresh_power_gates_and_wrong_gain_stop_before_any_run(self):
        for args in (['--prepare-off'],['--execute-three','missing'],['--restore-b-drive-off','missing']):
            with patch.object(board,'ORIGINAL_SETUP') as setup:
                with self.assertRaises(SystemExit):board.main(args)
                setup.assert_not_called()
        cfg='OK DOBFB ON=0 '+' '.join(k+'='+v for k,v in board.FB_CONFIG.items())
        for wrong in ('250000','1000000'):
            b=object.__new__(board.fb.FeedbackBoard);b.record={}
            with patch.object(board.fb,'FB_CONFIG',board.FB_CONFIG),patch.object(board.fb.shadow.ORIGINAL_BOARD,'command',
                    return_value=cfg.replace('GAIN_PPM=500000','GAIN_PPM='+wrong)) as send:
                with self.assertRaises(RuntimeError):b.command('MOTOR TEST MECH RUN POS 600')
                self.assertEqual(send.call_count,1)

    def test_exact_three_gainhalf_modes_closure_and_no_protection_retry(self):
        pmod=board.previous
        plan=dict(speeds_rpm=[600],ka_a_per_rpm_s=board.low.KA,overspeed_trip_rpm=1000,travel_limit_deg=30000)
        def parent():return dict(operator_present_whole_batch=True,attempts=[],runs=[])
        seen=[]
        def run(row,*args):
            seen.append((row['dob_feedback_gain'],board.fb.FEEDBACK_ON,args[-1]))
            row.update(pass_=True,final_outputs_off=True,final_cpu_halted=True,dob_control_enabled=True,final_capture='stopped')
        with patch.object(pmod,'GAIN',.5),patch.object(pmod,'SUMMARY_KEY','gainhalf_summary'),\
             patch.object(Path,'read_text',return_value=json.dumps(plan)),patch.object(Path,'read_bytes',return_value=b'flash'),\
             patch.object(pmod,'image',return_value=b'image'),patch.object(board.low.base,'staged',return_value=(Path('before'),b'flash')),\
             patch.object(board.low.prior,'new_run',side_effect=lambda name,*args:dict(receipt_path=name+'.json')),\
             patch.object(board.low.prior,'checkpoint'),patch.object(board.fb,'run_point',side_effect=run):
            p=parent();pmod.execute(Path('plan'),p)
            self.assertEqual(seen,[(.5,True,True),(.5,True,False),(.5,True,False)])
            self.assertEqual(p['dob_feedback_gain'],.5);self.assertEqual(p['gainhalf_summary']['runs'],3)
            with patch.object(board.fb,'run_point',side_effect=RuntimeError('independent protection')) as motor:
                with self.assertRaisesRegex(RuntimeError,'independent protection'):pmod.execute(Path('plan'),parent())
                self.assertEqual(motor.call_count,1)

if __name__=='__main__':unittest.main()
