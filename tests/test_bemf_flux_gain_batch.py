import collections
import hashlib
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
import bemf_flux_gain_batch as batch
from test_torque_chain import function
from test_torque350_five_second import expanded


class BatchTests(unittest.TestCase):
    def test_exact_image_frozen_functions_and_protection_objects(self):
        batch.image()
        normal=expanded('a','TighteningKa025Candidate')
        diagnostic=expanded('a','BemfFluxGainDiagnostic')
        for name in ('ProtectedLoop_AdcIrq','ProtectedLoop_PwmEntry','ProtectedLoop_SetDuty',
            'ProtectedLoop_TimerHealthy','ProtectedLoop_GuardIrqBody','PowerStage_Enable',
            'PowerStage_Disable','FOC_EncoderSpeedUpdate','Encoder_ElectricalAngleRad',
            'TighteningTask','MotorControlTask','MotorControl_SetIq'):
            self.assertEqual(function(normal,name),function(diagnostic,name),name)
        for name in ('stm32g4xx_it.c.obj','foc_adc_timing_stm32.c.obj',
            'as5047p_dma_stm32.c.obj','foc_zero_robust.c.obj','tightening_intent_fsm.c.obj'):
            a=next((ROOT/'foc2_app_a/build/TighteningKa025Candidate').rglob(name))
            b=next((ROOT/'foc2_app_a/build/BemfFluxGainDiagnostic').rglob(name))
            self.assertEqual(a.read_bytes(),b.read_bytes(),name)
        self.assertEqual(hashlib.sha256((ROOT/'foc2_app_b/build/FrictionBUnchanged/foc2.bin').read_bytes()).hexdigest(),
            '7ebdb56408baaa6c213c5dabe236250be673ed5a5c1345dfe64861d1e98dd366')

    def test_default_no_device_and_fresh_confirmation_gates(self):
        with patch.object(batch,'setup') as setup:
            for args in (['--prepare-off'],['--execute-fifteen','missing'],['--restore-b-drive-off','missing']):
                with self.assertRaises(SystemExit):batch.main(args)
            setup.assert_not_called()

    def test_three_per_level_and_missing_settling_not_zero(self):
        self.assertEqual(collections.Counter(batch.ORDER),{0:3,25:3,50:3,75:3,100:3})
        rows=[dict(metrics=dict(bemf_gain_percent=g,accel_mae_rpm=float(g),settling_time_ms=None)) for g in batch.ORDER]
        result=batch.summarize(rows)
        self.assertTrue(result['completed'])
        for group in result['groups'].values():
            self.assertEqual(group['runs'],3)
            self.assertEqual(group['metrics']['settling_time_ms']['missing'],3)
            self.assertIsNone(group['metrics']['settling_time_ms']['mean'])
        rows.reverse()
        with self.assertRaises(ValueError):batch.summarize(rows)

    def test_gain_readback_range_and_effective_flux(self):
        for percent in (0,25,50,75,100):
            line='OK BEMF ON=0 CONFIGURED=1 PSI_NWB=697320 DQ_CROSS=0 GAIN_PCT=%d EFFECTIVE_PSI_NWB=%d'%(percent,round(batch.PSI*percent*1e7))
            batch.gain_status(line,percent,False)
            with self.assertRaises(RuntimeError):batch.gain_status(line,percent,True)
        for value in (-1,101,True,25.0):
            with self.assertRaises(ValueError):batch.selected_psi(dict(bemf_gain_percent=value,manual_ka=batch.previous.KA,friction_enabled=True,bemf_enabled=True))

    def test_protection_stops_without_next_run(self):
        parent=dict(operator_present_whole_batch=True,attempts=[],runs=[],receipt_path='parent')
        row=dict(receipt_path='run',hardware_attempted=True,final_cpu_halted=True)
        with patch.object(Path,'read_text',return_value=json.dumps(dict(batch_order=list(batch.ORDER),batch_runs=15))),\
             patch.object(batch,'image',return_value=b'image'),patch.object(batch.base,'staged'),\
             patch.object(batch.prior,'checkpoint'),patch.object(batch.prior,'new_run',return_value=row),\
             patch.object(batch.base,'execute',side_effect=RuntimeError('protection')) as start,\
             patch.object(batch.prior,'next_run') as next_run:
            with self.assertRaisesRegex(RuntimeError,'protection'):batch.execute(Path('plan'),parent)
            self.assertEqual(start.call_count,1);next_run.assert_not_called()
            self.assertEqual(parent['runs'],[])

    def test_fifteen_runs_reuse_existing_protected_owner(self):
        parent=dict(operator_present_whole_batch=True,attempts=[],runs=[],receipt_path='parent')
        def new(*args):return dict(receipt_path='run'+str(args[-1]),final_outputs_off=True,final_cpu_halted=True)
        def metrics(row):return dict(bemf_gain_percent=row['bemf_gain_percent'])
        with patch.object(Path,'read_text',return_value=json.dumps(dict(batch_order=list(batch.ORDER),batch_runs=15))),\
             patch.object(batch,'image',return_value=b'image'),patch.object(batch.base,'staged'),\
             patch.object(batch.prior,'checkpoint'),patch.object(batch.prior,'new_run',side_effect=new),\
             patch.object(batch,'metrics',side_effect=metrics),patch.object(batch.base,'execute') as first,\
             patch.object(batch.prior,'next_run') as next_run:
            batch.execute(Path('plan'),parent)
            self.assertTrue(parent['pass_']);self.assertEqual(len(parent['runs']),15)
            self.assertEqual(first.call_count,1);self.assertEqual(next_run.call_count,14)


if __name__=='__main__':unittest.main()
