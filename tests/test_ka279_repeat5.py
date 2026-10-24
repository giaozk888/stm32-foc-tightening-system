import json
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
import ka279_repeat5 as batch

class RepeatTests(unittest.TestCase):
    def test_exact_five_original_owner_and_no_sixth(self):
        calls=[]
        def run(row,*args):
            calls.append(row['batch_index']);row.update(final_outputs_off=True,final_cpu_halted=True)
            row['metrics']=dict(manual_ka=batch.board.KA,accel_mae_rpm=float(row['batch_index']))
        plan=json.dumps(dict(batch_runs=5,manual_ka=batch.board.KA))
        with patch.object(Path,'read_text',return_value=plan),patch.object(batch.base,'staged'),\
             patch.object(batch.board,'image',return_value=b'image'),patch.object(batch.prior,'checkpoint'),\
             patch.object(batch.board,'execute',side_effect=run),patch.object(batch.prior,'next_run',side_effect=run),\
             patch.object(batch.board,'classify',side_effect=lambda r:r['metrics']),\
             patch.object(batch.board,'comparison',return_value={}):
            parent=dict(operator_present_whole_batch=True,receipt_path='fake',attempts=[],runs=[])
            batch.execute(Path('fake'),parent)
            self.assertEqual(calls,[1,2,3,4,5]);self.assertEqual(len(parent['attempts']),5)
            self.assertTrue(parent['pass_']);self.assertEqual(parent['summary']['metrics']['accel_mae_rpm']['mean'],3)

    def test_protection_stops_no_retry_no_advance(self):
        plan=json.dumps(dict(batch_runs=5,manual_ka=batch.board.KA))
        with patch.object(Path,'read_text',return_value=plan),patch.object(batch.base,'staged'),\
             patch.object(batch.board,'image',return_value=b'image'),patch.object(batch.prior,'checkpoint'),\
             patch.object(batch.board,'execute',side_effect=RuntimeError('protection')) as first,\
             patch.object(batch.prior,'next_run') as later:
            parent=dict(operator_present_whole_batch=True,receipt_path='fake',attempts=[],runs=[])
            with self.assertRaisesRegex(RuntimeError,'protection'):batch.execute(Path('fake'),parent)
            self.assertEqual(first.call_count,1);later.assert_not_called()

    def test_summary_missing_not_zero_and_mixed_gain_rejected(self):
        runs=[dict(metrics=dict(manual_ka=batch.board.KA,accel_mae_rpm=x,settling_time_ms=None)) for x in (1,2,3,4,5)]
        s=batch.summarize(runs);self.assertTrue(s['completed'])
        self.assertAlmostEqual(s['metrics']['accel_mae_rpm']['sd'],1.5811388300841898)
        self.assertIsNone(s['metrics']['settling_time_ms']['mean'])
        self.assertEqual(s['metrics']['settling_time_ms']['missing'],5)
        runs[0]['metrics']['manual_ka']=0
        with self.assertRaises(ValueError):batch.summarize(runs)

    def test_files_only_default_fresh_confirmation(self):
        p=subprocess.run([sys.executable,str(ROOT/'tools/ka279_repeat5.py')],capture_output=True,text=True)
        self.assertEqual(p.returncode,0,p.stdout+p.stderr);self.assertIn('no devices',p.stdout)
        with patch.object(batch.board,'setup') as setup:
            for args in (['--prepare-off'],['--execute-five','missing'],['--restore-b-drive-off','missing']):
                with self.assertRaises(SystemExit):batch.main(args)
            setup.assert_not_called()

if __name__=='__main__':unittest.main()
