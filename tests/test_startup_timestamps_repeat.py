import json
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch
from test_torque_chain import ROOT
sys.path.insert(0,str(ROOT/'tools'))
import startup_timestamps_repeat as repeat
gain=repeat.gain


class StartupRepeatTests(unittest.TestCase):
    def test_exact_six_no_seventh_and_calls_full_startup_classifier(self):
        plan=json.dumps(dict(batch_order=list(repeat.ORDER),batch_runs=6));calls=[]
        def run(row,*args):
            calls.append(row['gain_percent']);row.update(final_outputs_off=True,final_cpu_halted=True)
        def metrics(row):return dict(gain_percent=25,value=len(calls),startup_delays_ms=dict(t_iq_delay_us=62.9))
        with patch.object(Path,'read_text',return_value=plan),patch.object(gain.base,'staged'), \
             patch.object(gain,'image',return_value=b'image'),patch.object(gain.prior,'checkpoint'), \
             patch.object(gain.base,'execute',side_effect=run),patch.object(gain.prior,'next_run',side_effect=run), \
             patch.object(repeat.board,'classify',side_effect=metrics) as classify:
            parent=dict(operator_present_whole_batch=True,receipt_path='fake',attempts=[],runs=[])
            repeat.execute(Path('unused'),parent)
            self.assertEqual(calls,[25]*6);self.assertEqual(classify.call_count,6)
            self.assertTrue(parent['summary']['completed']);self.assertEqual(parent['summary']['metrics']['value']['mean'],3.5)
            self.assertEqual(parent['summary']['startup_relative_ms']['t_iq_ms']['mean'],62.9)

    def test_protection_or_timestamp_mismatch_stops_no_retry(self):
        plan=json.dumps(dict(batch_order=list(repeat.ORDER),batch_runs=6))
        for where in ('execute','classify'):
            with patch.object(Path,'read_text',return_value=plan),patch.object(gain.base,'staged'), \
                 patch.object(gain,'image',return_value=b'image'),patch.object(gain.prior,'checkpoint'), \
                 patch.object(gain.base,'execute',side_effect=RuntimeError('stop') if where=='execute' else None), \
                 patch.object(repeat.board,'classify',side_effect=RuntimeError('stop')), \
                 patch.object(gain.prior,'next_run') as later:
                parent=dict(operator_present_whole_batch=True,receipt_path='fake',attempts=[],runs=[])
                with self.assertRaisesRegex(RuntimeError,'stop'):repeat.execute(Path('unused'),parent)
                later.assert_not_called();self.assertEqual(len(parent['attempts']),1)

    def test_wrong_plan_or_missing_operator_never_executes(self):
        with patch.object(gain.base,'execute') as run:
            with self.assertRaises(ValueError):repeat.execute(Path('unused'),{})
            with patch.object(Path,'read_text',return_value=json.dumps(dict(batch_order=[25]*5,batch_runs=5))):
                with self.assertRaises(ValueError):repeat.execute(Path('unused'),dict(operator_present_whole_batch=True))
            run.assert_not_called()

    def test_sd_null_and_no_historical_pooling(self):
        r=[dict(metrics=dict(gain_percent=25,error=i,settling=None if i==0 else i,
            startup_delays_ms=dict(t_iq_delay_us=60+i))) for i in range(6)]
        s=repeat.summarize(r)
        self.assertEqual(s['metrics']['error']['mean'],2.5)
        self.assertAlmostEqual(s['metrics']['error']['sd'],1.8708286933869707)
        self.assertEqual(s['metrics']['settling']['missing'],1)
        self.assertEqual(s['startup_relative_ms']['t_iq_ms']['mean'],62.5)
        self.assertEqual(s['startup_relative_ms']['t_motion_ms']['n'],0)
        r[0]['metrics']['gain_percent']=100
        with self.assertRaises(ValueError):repeat.summarize(r)

    def test_files_only_default_and_confirmation_flags(self):
        p=subprocess.run([sys.executable,str(ROOT/'tools/startup_timestamps_repeat.py')],capture_output=True,text=True)
        self.assertEqual(p.returncode,0,p.stdout+p.stderr);self.assertIn('no devices',p.stdout)
        with patch.object(repeat.board,'setup') as setup:
            for args in (['--prepare-off'],['--execute-six','missing.json']):
                with self.assertRaises(SystemExit):repeat.main(args)
            setup.assert_not_called()

    def test_real_six_saved_captures_match_logs_and_statistics(self):
        batch=json.loads((ROOT/'tmp/startup-repeat-batch-1792649702871346200.json').read_text())
        self.assertTrue(batch['pass_']);self.assertEqual(len(batch['attempts']),6)
        self.assertEqual(repeat.summarize(batch['runs']),batch['summary'])
        for p in batch['attempts']:
            row=json.loads(Path(p).read_text())
            self.assertEqual(row['startup_saved'],repeat.board.startup.decode(Path(p),repeat.board.ELF))
            self.assertEqual(row['startup_saved']['snapshot']['valid'],31)
            self.assertEqual(repeat.board.check_logs(row),row['metrics']['startup_log_seq'])
            self.assertTrue(row['final_outputs_off'] and row['final_cpu_halted'] and row['all_app_private_unchanged'])


if __name__=='__main__':unittest.main()
