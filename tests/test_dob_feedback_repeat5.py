import json
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
import dob_feedback_repeat5 as board

class RepeatTests(unittest.TestCase):
    def test_files_only_frozen_image_actual_b1087_no_compile_or_hardware(self):
        p=subprocess.run([sys.executable,str(ROOT/'tools/dob_feedback_repeat5.py')],cwd=ROOT,text=True,capture_output=True)
        self.assertEqual(p.returncode,0,p.stdout+p.stderr);self.assertIn('no devices',p.stdout)
        r=json.loads(board.ROOT_RESTORE.read_text())
        self.assertEqual(r['metadata'][5],1087);self.assertTrue(r['pass_'] and r['b_application_not_run'])
        self.assertEqual(r['image_sha256'],board.fb.SHA)
        self.assertEqual(board.SCHEDULE,(False,True)*5)

    def test_fresh_operator_gates_before_setup(self):
        for args in (['--prepare-off'],['--execute-ten','missing'],['--restore-b-drive-off','missing']):
            with patch.object(board,'ORIGINAL_SETUP') as setup:
                with self.assertRaises(SystemExit):board.main(args)
                setup.assert_not_called()

    def test_all_ten_fixed_modes_output_closure_and_no_fault_retry(self):
        plan=dict(speeds_rpm=[600],ka_a_per_rpm_s=board.low.KA,overspeed_trip_rpm=1000,travel_limit_deg=30000)
        def parent():return dict(operator_present_whole_batch=True,attempts=[],runs=[])
        seen=[]
        def run(row,name,source,before,data,rpm,first):
            seen.append((board.fb.FEEDBACK_ON,rpm,first))
            row.update(pass_=True,final_outputs_off=True,final_cpu_halted=True,
                dob_control_enabled=board.fb.FEEDBACK_ON,final_capture='stopped',
                accel_ff_ram_stats=dict(accel_error_integral=2,accel_time_s=1),
                feedback_capture=dict(peak_a=.001 if board.fb.FEEDBACK_ON else 0))
        def new(name,*args):return dict(receipt_path=name+'.json')
        with patch.object(Path,'read_text',return_value=json.dumps(plan)),patch.object(Path,'read_bytes',return_value=b'flash'),\
             patch.object(board.fb,'image',return_value=b'image'),patch.object(board.low.base,'staged',return_value=(Path('before'),b'flash')),\
             patch.object(board.low.prior,'new_run',side_effect=new),patch.object(board.low.prior,'checkpoint'),\
             patch.object(board.fb,'run_point',side_effect=run):
            p=parent();board.execute(Path('plan'),p)
            self.assertEqual(seen,[(x,600,i==0) for i,x in enumerate(board.SCHEDULE)])
            self.assertTrue(p['pass_']);self.assertEqual(len(p['runs']),10)
            self.assertEqual(p['comparison']['groups']['ON']['runs'],5)
            self.assertEqual(p['comparison']['groups']['OFF']['runs'],5)
            self.assertEqual(len(p['comparison']['pairs']),5)
            seen.clear()
            with patch.object(board.fb,'run_point',side_effect=RuntimeError('independent protection')) as motor:
                with self.assertRaisesRegex(RuntimeError,'independent protection'):board.execute(Path('plan'),parent())
                self.assertEqual(motor.call_count,1)
            with patch.object(board.fb,'run_point',side_effect=lambda row,*args:row.update(pass_=True,
                final_outputs_off=False,final_cpu_halted=True,dob_control_enabled=False)) as motor:
                with self.assertRaisesRegex(RuntimeError,'no next run'):board.execute(Path('plan'),parent())
                self.assertEqual(motor.call_count,1)

    def test_actual_prior_pair_metrics_units_and_statistics(self):
        rows=[json.loads((ROOT/'tmp'/p).read_text()) for p in (
            'mechanical-ident-run-1792736271628104000.json','mechanical-ident-run-1792736471931434600.json')]
        s=board.summarize(rows)
        self.assertAlmostEqual(s['groups']['OFF']['metrics']['accel_mae_rpm']['mean'],6.9535898353)
        self.assertAlmostEqual(s['groups']['ON']['metrics']['comp_peak_a']['mean'],.0056587653)
        self.assertGreater(s['pairs'][0]['on_minus_off']['accel_mae_rpm'],0)
        with self.assertRaises(ValueError):board.summarize(rows[::-1])

if __name__=='__main__':unittest.main()
