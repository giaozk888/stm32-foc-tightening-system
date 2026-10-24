import json
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch
from test_torque_chain import ROOT
sys.path.insert(0,str(ROOT/'tools'))
import accel_ff_repeat025 as repeat
batch=repeat.batch


class Repeat025Tests(unittest.TestCase):
    def test_exact_five_no_sixth_and_fault_stops(self):
        plan=json.dumps(dict(batch_order=list(repeat.ORDER),batch_runs=5));calls=[]
        def run(row,*args):
            calls.append(row['gain_percent']);row.update(final_outputs_off=True,final_cpu_halted=True)
        def metrics(row):return dict(gain_percent=row['gain_percent'],value=len(calls))
        with patch.object(Path,'read_text',return_value=plan),patch.object(batch.base,'staged'), \
             patch.object(batch,'image',return_value=b'image'),patch.object(batch.prior,'checkpoint'), \
             patch.object(batch.base,'execute',side_effect=run),patch.object(batch.prior,'next_run',side_effect=run), \
             patch.object(batch,'metrics',side_effect=metrics):
            parent=dict(operator_present_whole_batch=True,receipt_path='fake',attempts=[],runs=[])
            repeat.execute(Path('unused'),parent)
            self.assertEqual(calls,[25]*5);self.assertEqual(len(parent['runs']),5)
            self.assertTrue(parent['summary']['completed']);self.assertEqual(parent['summary']['metrics']['value']['mean'],3)
        with patch.object(Path,'read_text',return_value=plan),patch.object(batch.base,'staged'), \
             patch.object(batch,'image',return_value=b'image'),patch.object(batch.prior,'checkpoint'), \
             patch.object(batch.base,'execute',side_effect=RuntimeError('protection')), \
             patch.object(batch.prior,'next_run') as next_run:
            parent=dict(operator_present_whole_batch=True,receipt_path='fake',attempts=[],runs=[])
            with self.assertRaisesRegex(RuntimeError,'protection'):repeat.execute(Path('unused'),parent)
            next_run.assert_not_called();self.assertEqual(len(parent['attempts']),1)

    def test_requires_five_plan_and_operator_before_any_execution(self):
        with patch.object(batch.base,'execute') as run:
            with self.assertRaises(ValueError):repeat.execute(Path('unused'),{})
            with patch.object(Path,'read_text',return_value=json.dumps(dict(batch_order=[25]*6,batch_runs=6))):
                with self.assertRaises(ValueError):repeat.execute(Path('unused'),dict(operator_present_whole_batch=True))
            run.assert_not_called()

    def test_sd_missing_settling_not_zero_and_no_mixed_gains(self):
        r=[dict(metrics=dict(gain_percent=25,value=i,settling=None if i==0 else i)) for i in range(5)]
        s=repeat.summarize(r)
        self.assertEqual(s['metrics']['value']['mean'],2)
        self.assertAlmostEqual(s['metrics']['value']['sd'],1.5811388300841898)
        self.assertEqual(s['metrics']['settling']['n'],4);self.assertEqual(s['metrics']['settling']['missing'],1)
        r[0]['metrics']['gain_percent']=50
        with self.assertRaises(ValueError):repeat.summarize(r)

    def test_same_image_default_is_files_only_and_flags_gate_devices(self):
        p=subprocess.run([sys.executable,str(ROOT/'tools/accel_ff_repeat025.py')],capture_output=True,text=True)
        self.assertEqual(p.returncode,0,p.stdout+p.stderr);self.assertIn('no devices',p.stdout)
        with patch.object(batch,'setup') as setup:
            for args in (['--prepare-off'],['--execute-five','missing.json']):
                with self.assertRaises(SystemExit):repeat.main(args)
            setup.assert_not_called()


if __name__=='__main__':unittest.main()
