"""No hardware: nine explicit points; quality continues, unsafe never retries."""
import copy
import json
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
import motor_ident_rs_repeat_batch as batch
import test_motor_identification as fixtures


def historic(name,ma):
    r=json.loads((ROOT/'tmp'/name).read_text())
    r['ma']=ma
    return r


class RsRepeatBatchTests(unittest.TestCase):
    def test_files_pins_and_offline_default(self):
        self.assertEqual(len(batch.image()),215132)
        with patch.dict(batch.base.__dict__,{}):
            batch.configure();self.assertEqual(batch.base.EXPECT_META[2:6],(2,0,0,856))
        p=subprocess.run([sys.executable,str(ROOT/'tools/motor_ident_rs_repeat_batch.py')],
                         capture_output=True,text=True,timeout=15)
        self.assertEqual(p.returncode,0,p.stdout+p.stderr)
        self.assertIn('fixed 9-point Rs batch; no devices',p.stdout)

    def test_historical_quality_not_safety_and_original_thresholds(self):
        good=historic('motor-ident-rs50-run-1792556483256768500.json',50)
        self.assertEqual(batch.classify(good),'QUALIFIED')
        for name,ma in (('motor-ident-rs75-run-1792556826437979800.json',75),
                        ('motor-ident-rs100-run-1792557053888043300.json',100)):
            r=historic(name,ma)
            self.assertEqual(batch.classify(r),'QUALITY_FAILED')
        for key in ('final_cpu_halted','final_outputs_off','all_app_private_unchanged','preflight_pass'):
            r=copy.deepcopy(good);r[key]=False
            self.assertNotIn(batch.classify(r),('QUALIFIED','QUALITY_FAILED'))
        for change in ('encoder','deadline','CCR','fault','unknown_ack','motion','missing_safe','transport'):
            r=copy.deepcopy(good)
            if change=='encoder':r['encoder_terminal_saved']['counters']['timeouts']=1
            elif change=='deadline':r['snapshot']['timing']['deadline_miss']=1
            elif change=='CCR':r['snapshot']['timing']['actual_late_count']=1
            elif change=='fault':r['live_guard']['cl_flags']=1
            elif change=='unknown_ack':r.pop('excitation_ack')
            elif change=='motion':
                r['ident_ram'].update(status=4,reason=2);r['terminal_ident'].update(STATUS='4',REASON='2')
            elif change=='missing_safe':r['safe']['SD']='1'
            elif change=='transport':r['operation_error']='No ACK'
            self.assertNotIn(batch.classify(r),('QUALIFIED','QUALITY_FAILED'),change)

    def exercise(self,outcomes):
        seen=[]
        def point(row,name,source,before,data,first):
            seen.append((row['ma'],row['repeat'],first))
            row.update(point_outcome=outcomes[len(seen)-1],final_capture='unused',final_sha256='same',
                       final_cpu_halted=True,final_outputs_off=True)
            row['ident_run']=fixtures.rs_run(row['ma']/1000)
            row['single_point_observation']=dict(mean_id_a=row['ma']/1000,mean_iq_a=0,mean_vd_v=.002+.1*row['ma']/1000)
        parent=dict(powered_no_alarm=True,locked_fixture=True)
        with patch.object(batch.base,'staged',return_value=(Path('unused'),b'x')),\
             patch.object(batch.base.old.prior,'checkpoint'),\
             patch.object(Path,'read_bytes',return_value=b'x'),\
             patch.object(batch.base.old.zero,'digest',return_value='same'),\
             patch.object(batch.time,'sleep'),patch.dict(batch.run.__dict__,{}):
            batch.execute_batch(parent,'offline',Path('unused'),b'x',point_runner=point)
        return seen,parent

    def test_all_nine_quality_failures_retained_not_stop_or_promoted(self):
        seen,parent=self.exercise(['QUALITY_FAILED']*9)
        self.assertEqual([(m,r) for m,r,_ in seen],list(batch.PLAN))
        self.assertEqual([f for _,_,f in seen],[True]+[False]*8)
        self.assertTrue(parent['pass_']);self.assertFalse(parent['all_quality_pass'])
        self.assertEqual(parent['remaining_not_run'],[])
        self.assertEqual(len(parent['comparison']['points']),9)
        self.assertIsNone(parent['comparison']['qualified_rs'])
        self.assertTrue(all(v['qualified']==0 for v in parent['comparison']['by_current'].values()))

    def test_safety_fault_ends_batch_no_next_reset_no_retry(self):
        seen,parent=self.exercise(['QUALITY_FAILED','PROTECTION_STOP'])
        self.assertEqual(len(seen),2);self.assertFalse(parent['pass_'])
        self.assertEqual(len(parent['remaining_not_run']),7)
        self.assertEqual(parent['safety_stop'],'PROTECTION_STOP')

    def test_qualified_fit_separate_from_all_observations_and_proof_required(self):
        seen,parent=self.exercise(['QUALIFIED']*9)
        self.assertEqual(len(seen),9)
        self.assertAlmostEqual(parent['comparison']['qualified_rs']['rs_ohm'],.1)
        self.assertFalse(parent['comparison']['automatic_pi_write'])
        with patch.object(batch.base,'staged') as staged:
            with self.assertRaises(ValueError):batch.execute_batch({},'no',Path('unused'),b'')
        staged.assert_not_called()

    def test_fresh_one_shot_each_boot_no_fault_clearing_or_firmware_write(self):
        import inspect
        code=inspect.getsource(batch.run_point)
        self.assertIn('if first:',code)
        self.assertEqual(code.count('write_mailbox('),1)
        self.assertNotIn('CONFIRM_CURRENT',code)
        self.assertNotIn('flash write',code)
        self.assertNotIn('CLEAR',code)
        self.assertIn('wait_health_confirmation',code)
        self.assertIn('wait_timing',code)
        self.assertIn('capture_stopped',code)


if __name__=='__main__':unittest.main()
