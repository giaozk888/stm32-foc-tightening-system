import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
import dq_repeat_batch as b


def good(on=False):
    return dict(dq_enabled=on,start_attempts=1,preflight_pass=True,
        final_outputs_off=True,final_cpu_halted=True,all_app_private_unchanged=True,
        outputs=dict(VTOR=0x08008000,DHCSR=0x30003,SD=0,BDTR=0,CCER=0),
        postflight={'MOTOR TEST FAULT':'1 OK MOTOR TEST FAULT VALID=0 FLAGS=0'},
        terminal_status=dict(FLT='0',CONTACT='0',OUTCOME='RUNDOWN_TIMEOUT'),
        fsm_observation_complete=True,
        snapshot=dict(timing=dict(deadline_miss=0,actual_late_count=0,wall_max_us=33,
                                 actual_margin_min_us=15),cur_confirm=dict(fault=0)),
        encoder_saved=dict(first_fault=dict(valid=0),counters=dict(timeouts=0,dma_errors=0,
                           schedule_misses=0,control_stale=0)),
        friction_metrics={'POS':dict(N=8000,START_MS=325,CRUISE_MAE_MRPM=3500,
            LOW_MAE_MRPM=12000,IQ_REF_PEAK_MA=400,IQ_MEAS_PEAK_MA=1100,I_PEAK_MA=100,PI_PEAK_MA=250)},
        accel_ff_metrics=dict(N=8000,ACC_MAE_MRPM=10000,OV_MRPM=6000,SETTLE_MS=7000),
        speed_summary=dict(tail_mean_rpm=239,tracking_pass=True),zero=dict(zero_u=1560,zero_v=1563))


class BatchTests(unittest.TestCase):
    def test_exact_six_alternating_fixed_no_auto_sign_or_current_steps(self):
        self.assertEqual(b.ORDER,(False,True,False,True,False,True))
        self.assertEqual(sum(b.ORDER),3)

    def test_fault_shutdown_or_timing_failure_prevents_next_run(self):
        paths=[('outputs','SD',64),('outputs','BDTR',0x8000),
            ('terminal_status','FLT','1'),('terminal_status','CONTACT','1')]
        for a,key,value in paths:
            row=good();row[a][key]=value
            with self.assertRaises(RuntimeError):b.classify(row)
        for key in ('deadline_miss','actual_late_count'):
            row=good();row['snapshot']['timing'][key]=1
            with self.assertRaises(RuntimeError):b.classify(row)
        for key in ('timeouts','dma_errors','schedule_misses','control_stale'):
            row=good();row['encoder_saved']['counters'][key]=1
            with self.assertRaises(RuntimeError):b.classify(row)
        row=good();row['start_attempts']=2
        with self.assertRaises(RuntimeError):b.classify(row)

    def test_quality_failure_is_preserved_not_replaced_or_silently_omitted(self):
        row=good();row['speed_summary']['tracking_pass']=False
        row['speed_summary']['tail_mean_rpm']=180
        self.assertEqual(b.classify(row)['tail_mean_rpm'],180)
        row['friction_metrics']['POS']['START_MS']=-1
        self.assertIsNone(b.classify(row)['stable_motion_delay_ms'])

    def test_mean_sd_and_missing_metrics_are_not_zero_filled(self):
        rows=[]
        for i,on in enumerate(b.ORDER):
            m=b.classify(good(on));m['accel_mae_rpm']=float(i)
            if i==0:m['stable_motion_delay_ms']=None
            rows.append(dict(metrics=m))
        s=b.summarize(rows)
        self.assertTrue(s['completed'])
        self.assertEqual(s['groups']['OFF']['metrics']['accel_mae_rpm']['mean'],2)
        self.assertEqual(s['groups']['ON']['metrics']['accel_mae_rpm']['mean'],3)
        self.assertEqual(s['groups']['OFF']['metrics']['accel_mae_rpm']['sd'],2)
        self.assertEqual(s['groups']['OFF']['metrics']['stable_motion_delay_ms']['missing'],1)
        self.assertEqual(s['on_minus_off_mean']['accel_mae_rpm'],1)

    def test_physical_assertions_required_before_device_or_setup(self):
        with patch.object(b,'setup') as setup,patch.object(b.base.hw,'debug') as device:
            for args in (['--prepare-off'],['--execute-six','missing.json']):
                with self.assertRaises(SystemExit):b.main(args)
            setup.assert_not_called();device.assert_not_called()

    def test_batch_fault_is_saved_and_no_further_slot_is_launched(self):
        plan=dict(batch_order=list(b.ORDER),batch_runs=6,dq_enabled=False)
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'plan.json';path.write_text(json.dumps(plan))
            parent=dict(receipt_path='mock',attempts=[],runs=[])
            def execute(row,*args):
                row['hardware_attempted']=True;row.update(good(False));row['outputs']['SD']=64
                raise RuntimeError('Protection fault; no retry')
            with patch.object(b.base,'staged'),patch.object(b,'checkpoint'),patch.object(b.original,'image',return_value=b''),\
                 patch.object(b.base,'execute',side_effect=execute) as first,patch.object(b,'next_run') as next_run,\
                 patch.object(b.base.hw,'emergency_off') as off:
                with self.assertRaisesRegex(RuntimeError,'Protection fault'):b.execute_batch(path,parent)
                first.assert_called_once();next_run.assert_not_called();off.assert_called_once()
                self.assertEqual(parent['runs'],[]);self.assertEqual(len(parent['attempts']),1)

    def test_failed_previous_cannot_be_reset_for_next_slot(self):
        previous=good();previous['encoder_saved']['counters']['timeouts']=1
        with patch.object(b.base.hw,'debug') as debug,patch.object(b.base.support.support,'open_port') as serial:
            with self.assertRaises(RuntimeError):b.next_run({},'unused',previous)
            debug.assert_not_called();serial.assert_not_called()

    def test_success_runs_exactly_six_and_preserves_timeout_not_tightening_OK(self):
        plan=dict(batch_order=list(b.ORDER),batch_runs=6,dq_enabled=False)
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'plan.json';path.write_text(json.dumps(plan))
            parent=dict(receipt_path='mock',attempts=[],runs=[])
            def fill(row,*args):
                on=row['dq_enabled'];row.update(good(on));row['hardware_attempted']=True
                row['final_capture']='mock.bin'
            def first(row,*args):
                fill(row)
                raise RuntimeError('FSM terminal RUNDOWN_TIMEOUT; no-load observation is not successful tightening; no retry')
            with patch.object(b.base,'staged'),patch.object(b,'checkpoint'),patch.object(b.original,'image',return_value=b''),\
                 patch.object(b.base,'execute',side_effect=first) as first_call,\
                 patch.object(b,'next_run',side_effect=fill) as rest,patch.object(b,'add_decode'):
                b.execute_batch(path,parent)
            first_call.assert_called_once();self.assertEqual(rest.call_count,5)
            self.assertEqual([r['metrics']['mode'] for r in parent['runs']],['OFF','ON']*3)
            self.assertTrue(parent['summary']['completed']);self.assertTrue(parent['final_outputs_off'])
            self.assertEqual(len(parent['attempts']),6)


if __name__=='__main__':unittest.main()
