import copy
import json
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch
from test_torque_chain import ROOT
sys.path.insert(0,str(ROOT/'tools'))
import ka_identification_repeat as repeat


class KaRepeatTests(unittest.TestCase):
    def test_five_exact_no_sixth_even_untrusted_fit(self):
        plan=json.dumps(dict(batch_order=[0]*5,batch_runs=5,startup_exclusion_us=600000));calls=[]
        def run(row,*args):calls.append(row['gain_percent']);row.update(final_outputs_off=True,final_cpu_halted=True)
        fit=dict(full=dict(directions=[dict(direction=1,trusted=False,ka_identified=-.01)]),
            post_startup=[dict(direction=1,trusted=False,ka_identified=None)])
        with patch.object(Path,'read_text',return_value=plan),patch.object(repeat.base,'staged'), \
            patch.object(repeat.board,'image',return_value=b'image'),patch.object(repeat.prior,'checkpoint'), \
            patch.object(repeat.base,'execute',side_effect=run),patch.object(repeat.prior,'next_run',side_effect=run), \
            patch.object(repeat.board,'classify',return_value=dict(ka_compile_time=0,accel_mae_rpm_full_precision=12)), \
            patch.object(repeat.board.identification,'decode',return_value={}),patch.object(repeat,'analyze',return_value=fit):
            parent=dict(operator_present_whole_batch=True,receipt_path='fake',attempts=[],runs=[])
            repeat.execute(Path('fake'),parent)
            self.assertEqual(calls,[0]*5);self.assertTrue(parent['pass_'])
            self.assertEqual(parent['summary']['fits']['full']['trusted_only']['n'],0)

    def test_protection_stops_not_quality_failure(self):
        plan=json.dumps(dict(batch_order=[0]*5,batch_runs=5,startup_exclusion_us=600000))
        with patch.object(Path,'read_text',return_value=plan),patch.object(repeat.base,'staged'), \
            patch.object(repeat.board,'image',return_value=b'image'),patch.object(repeat.prior,'checkpoint'), \
            patch.object(repeat.base,'execute',side_effect=RuntimeError('protection')),patch.object(repeat.prior,'next_run') as later:
            parent=dict(operator_present_whole_batch=True,receipt_path='fake',attempts=[],runs=[])
            with self.assertRaisesRegex(RuntimeError,'protection'):repeat.execute(Path('fake'),parent)
            later.assert_not_called();self.assertEqual(len(parent['attempts']),1)

    def test_plan_and_operator_required(self):
        with self.assertRaises(ValueError):repeat.execute(Path('fake'),{})
        with patch.object(Path,'read_text',return_value='{}'),patch.object(repeat.base,'staged') as staged:
            with self.assertRaises(ValueError):repeat.execute(Path('fake'),dict(operator_present_whole_batch=True))
            staged.assert_not_called()

    def test_startup_separation_predeclared_not_residual_or_stable(self):
        r=json.loads((ROOT/'tmp/ka-ident-run-1792652514849299800.json').read_text())
        a=repeat.analyze(r['ka_capture']);self.assertEqual(a['startup_exclusion_us'],600000)
        f=a['post_startup'][0]
        self.assertTrue(all(x['seq']>=7 for x in f['accepted']))
        self.assertEqual(len(a['full']['directions'][0]['accepted']),20)
        modified=copy.deepcopy(r['ka_capture']);modified['t_stable_us']=99999999
        self.assertEqual(repeat.analyze(modified),a)

    def test_default_files_only_and_confirmation_before_setup(self):
        p=subprocess.run([sys.executable,str(ROOT/'tools/ka_identification_repeat.py')],text=True,capture_output=True)
        self.assertEqual(p.returncode,0,p.stdout+p.stderr);self.assertIn('no devices',p.stdout)
        with patch.object(repeat.board,'setup') as setup:
            for args in (['--prepare-off'],['--execute-five','missing'],['--restore-b-drive-off','missing']):
                with self.assertRaises(SystemExit):repeat.main(args)
            setup.assert_not_called()


if __name__=='__main__':unittest.main()
