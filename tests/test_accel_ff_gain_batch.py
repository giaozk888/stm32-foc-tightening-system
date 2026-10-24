import json
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch
from test_torque_chain import ROOT,GCC
sys.path.insert(0,str(ROOT/'tools'))
import accel_ff_gain_batch as batch


class AccelGainBatchTests(unittest.TestCase):
    def test_real_c_idle_only_binding_and_bounded_parser(self):
        exe=ROOT/'tmp/accel-gain-binding.exe'
        p=subprocess.run([GCC,'-std=c11','-Os','-Wall','-Wextra','-Werror','-UNDEBUG',
            '-I',str(ROOT/'firmware_common'),str(ROOT/'tests/accel_gain_binding_host.c'),
            str(ROOT/'firmware_common/speed_accel_audit.c'),
            str(ROOT/'firmware_common/speed_accel_feedforward.c'),'-o',str(exe)],capture_output=True,text=True)
        self.assertEqual(p.returncode,0,p.stdout+p.stderr)
        p=subprocess.run([str(exe)],capture_output=True,text=True)
        self.assertEqual(p.returncode,0,p.stdout+p.stderr)

    def test_exact_six_and_no_retry_after_protection(self):
        plan=json.dumps(dict(batch_order=list(batch.ORDER),batch_runs=6));calls=[]
        def run(row,*args):
            calls.append(row['gain_percent']);row.update(final_outputs_off=True,final_cpu_halted=True)
        def metrics(row):return dict(gain_percent=row['gain_percent'],value=1)
        with patch.object(Path,'read_text',return_value=plan),patch.object(batch.base,'staged'), \
             patch.object(batch,'image',return_value=b'image'),patch.object(batch.prior,'checkpoint'), \
             patch.object(batch.base,'execute',side_effect=run),patch.object(batch.prior,'next_run',side_effect=run), \
             patch.object(batch,'metrics',side_effect=metrics):
            parent=dict(operator_present_whole_batch=True,receipt_path='fake',attempts=[],runs=[])
            batch.execute(Path('unused'),parent)
            self.assertEqual(calls,list(batch.ORDER));self.assertEqual(len(parent['runs']),6)
            self.assertTrue(parent['summary']['completed'])
        with patch.object(Path,'read_text',return_value=plan),patch.object(batch.base,'staged'), \
             patch.object(batch,'image',return_value=b'image'),patch.object(batch.prior,'checkpoint'), \
             patch.object(batch.base,'execute',side_effect=RuntimeError('protection')), \
             patch.object(batch.prior,'next_run') as later:
            parent=dict(operator_present_whole_batch=True,receipt_path='fake',attempts=[],runs=[])
            with self.assertRaisesRegex(RuntimeError,'protection'):batch.execute(Path('unused'),parent)
            later.assert_not_called();self.assertEqual(len(parent['attempts']),1)

    def test_readback_exact_gain_friction_and_pairwise_not_mixed_on_average(self):
        for gain in batch.ORDER:
            with patch.object(batch,'current_gain',gain):
                ka=round(.0001875*gain/100*1e9);peak=round(.0375*gain/100*1e6)
                batch.ff_status(f'OK AFF ON=1 KA_NA_PER_RPM_S={ka} ACCEL_MAX_RPM_S=200 FF_PEAK_UA={peak} TOKENIZED=1')
                batch.friction_status(f'OK FRC ON=1 I_UA=105000 DB_MRPM=2000 FF_ON=1 KA_NA_PER_RPM_S={ka} TOKENIZED=1',True)
                with self.assertRaises(RuntimeError):batch.ff_status('OK AFF ON=0')
        s=batch.summarize([dict(metrics=dict(gain_percent=g,error=i,settling=None)) for i,g in enumerate(batch.ORDER)])
        self.assertTrue(s['completed']);self.assertEqual([p['gain_percent'] for p in s['paired']],[25,50,100])
        self.assertTrue(all(p['candidate_minus_baseline']['error']==1 for p in s['paired']))
        self.assertTrue(all('settling' not in p['candidate_minus_baseline'] for p in s['paired']))

    def test_offline_verifier_and_no_devices_default(self):
        p=subprocess.run([sys.executable,str(ROOT/'tools/accel_ff_gain_batch.py')],capture_output=True,text=True)
        self.assertEqual(p.returncode,0,p.stdout+p.stderr);self.assertIn('no devices',p.stdout)
        with patch.object(batch,'setup') as setup:
            for args in (['--prepare-off'],['--execute-six','missing.json']):
                with self.assertRaises(SystemExit):batch.main(args)
            setup.assert_not_called()


if __name__=='__main__':unittest.main()
