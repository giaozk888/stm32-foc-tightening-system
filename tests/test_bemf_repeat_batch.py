"""Fixed-six BEMF comparison, mocked hardware and real saved-data gates."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch
from test_torque_chain import ROOT
from test_bemf_fitted_fsm_board import BemfFittedTests
sys.path.insert(0,str(ROOT/'tools'))
import bemf_repeat_batch as batch
import bemf_fitted_fsm_board as fitted


class BemfRepeatTests(unittest.TestCase):
    def test_off_and_on_real_classifier_retains_formula_and_fault_gates(self):
        for on in (False,True):
            r=BemfFittedTests.row();r['bemf_enabled']=on
            r['bemf_samples'][0]['values'].update(ON=str(int(on)),VQ_FF_UV='174330' if on else '0')
            self.assertTrue(fitted.classify(r)['acquisition_complete'])
            r['bemf_samples'][0]['values']['ON']=str(int(not on))
            with self.assertRaises(RuntimeError):fitted.classify(r)
        r=BemfFittedTests.row();r['bemf_enabled']=False
        r['bemf_samples'][0]['values']['ON']='0'
        with self.assertRaises(RuntimeError):fitted.classify(r) # OFF must not emit FF.

    def test_same_query_load_and_single_switch_before_motion_both_modes(self):
        self.assertEqual(batch.BatchBoard.query_interval_s,.5)
        class Board:
            def __init__(self):self.commands=[]
            def command(self,cmd):
                self.commands.append(cmd)
                return '1 OK BEMF ON='+('1' if cmd.endswith(' ON') else '0')+' CONFIGURED=1 PSI_NWB=697320 DQ_CROSS=0'
        for on in (False,True):
            b=Board();row=dict(bemf_enabled=on)
            with patch.object(fitted,'ORIGINAL_MOTION') as motion:
                fitted.motion(b,row);motion.assert_called_once_with(b,row)
            self.assertEqual(b.commands,['MOTOR TEST BEMF STATUS','MOTOR TEST BEMF '+('ON' if on else 'OFF')])

    def test_exact_six_alternating_no_seventh_and_protection_stops(self):
        plan=json.dumps(dict(batch_order=list(batch.ORDER),batch_runs=6))
        calls=[]
        def run(row,*args):
            calls.append(row['bemf_enabled']);row.update(final_outputs_off=True,final_cpu_halted=True)
        def metrics(row):return dict(mode='ON' if row['bemf_enabled'] else 'OFF',value=1)
        with patch.object(Path,'read_text',return_value=plan),patch.object(batch.base,'staged'), \
             patch.object(fitted,'image',return_value=b'image'),patch.object(batch,'checkpoint'), \
             patch.object(batch.base,'execute',side_effect=run),patch.object(batch,'next_run',side_effect=run), \
             patch.object(batch,'metrics',side_effect=metrics):
            parent=dict(operator_present_whole_batch=True,receipt_path='fake',attempts=[],runs=[])
            batch.execute(Path('unused'),parent)
            self.assertEqual(calls,list(batch.ORDER));self.assertEqual(len(parent['runs']),6)
            self.assertTrue(parent['summary']['completed'])
        with patch.object(Path,'read_text',return_value=plan),patch.object(batch.base,'staged'), \
             patch.object(fitted,'image',return_value=b'image'),patch.object(batch,'checkpoint'), \
             patch.object(batch.base,'execute',side_effect=RuntimeError('protected')), \
             patch.object(batch,'next_run') as next_run:
            parent=dict(operator_present_whole_batch=True,receipt_path='fake',attempts=[],runs=[])
            with self.assertRaisesRegex(RuntimeError,'protected'):batch.execute(Path('unused'),parent)
            next_run.assert_not_called();self.assertEqual(len(parent['attempts']),1)

    def test_wrong_plan_or_missing_operator_never_starts(self):
        with patch.object(batch.base,'execute') as run:
            with self.assertRaises(ValueError):batch.execute(Path('unused'),{})
            with patch.object(Path,'read_text',return_value=json.dumps(dict(batch_order=[True]*6,batch_runs=6))):
                with self.assertRaises(ValueError):batch.execute(Path('unused'),dict(operator_present_whole_batch=True))
            run.assert_not_called()

    def test_means_sd_missing_settling_not_zero_and_bad_quality_not_discarded(self):
        rows=[dict(metrics=dict(mode='ON' if on else 'OFF',error=float(i),settling=None if i==1 else i))
              for i,on in enumerate(batch.ORDER)]
        s=batch.summarize(rows)
        self.assertTrue(s['completed']);self.assertEqual(s['groups']['OFF']['metrics']['error']['mean'],2)
        self.assertEqual(s['groups']['ON']['metrics']['error']['mean'],3)
        self.assertEqual(s['on_minus_off_mean']['error'],1)
        self.assertEqual(s['groups']['ON']['metrics']['settling']['missing'],1)
        self.assertEqual(s['groups']['ON']['metrics']['settling']['n'],2)
        self.assertEqual(s['groups']['OFF']['metrics']['error']['sd'],2)

    def test_no_hardware_default_and_confirmation_flags(self):
        with patch.object(batch,'setup') as setup:
            self.assertEqual(batch.main([]),0);setup.assert_called_once()
        with patch.object(batch,'setup') as setup:
            for args in (['--prepare-off'],['--execute-six','missing.json']):
                with self.assertRaises(SystemExit):batch.main(args)
            setup.assert_not_called()
        p=subprocess.run([sys.executable,str(ROOT/'tools/bemf_repeat_batch.py')],text=True,capture_output=True)
        self.assertEqual(p.returncode,0,p.stdout+p.stderr);self.assertIn('no devices',p.stdout)

    def test_full_aggregate_counts_required_and_old_poor_run_retained(self):
        r=json.loads((ROOT/'tmp/bemf-fitted-run-1792642731451485100.json').read_text())
        m=batch.metrics(r)
        self.assertEqual(m['accel_mae_rpm'],22.302)
        self.assertEqual(m['uart_dropped_bytes'],150)
        self.assertEqual(m['mode'],'ON')
        r['accel_ff_metrics']['N']=7999
        with self.assertRaises(RuntimeError):batch.metrics(r)


if __name__=='__main__':unittest.main()
