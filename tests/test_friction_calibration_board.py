"""Batch orchestration contracts, exclusively mocked hardware."""
import json
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch,Mock
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
import friction_calibration_board as board
import friction_calibration_comparison as comparison


class BatchTests(unittest.TestCase):
    def test_default_validates_files_without_devices(self):
        p=subprocess.run([sys.executable,str(ROOT/'tools/friction_calibration_board.py')],
            text=True,capture_output=True,timeout=15)
        self.assertEqual(p.returncode,0,p.stdout+p.stderr)
        self.assertIn('OFFLINE PASS: no device access',p.stdout)

    def test_no_physical_confirmation_no_devices(self):
        with patch.object(board.base,'staged') as stage,patch.object(board.base.hw,'debug') as debug:
            with self.assertRaises(ValueError):board.execute({},'none',Path('none'),b'')
            stage.assert_not_called();debug.assert_not_called()
        p=subprocess.run([sys.executable,str(ROOT/'tools/friction_calibration_board.py'),'--execute-batch','missing.json'],
            text=True,capture_output=True,timeout=15)
        self.assertEqual(p.returncode,2)

    def test_fault_ends_grid_without_next_point(self):
        row=board.new_row('mock','run');row['powered_no_alarm']=True
        def fail(child,*args):
            child.update(final_cpu_halted=True,final_outputs_off=True)
            raise RuntimeError('protection fault')
        with patch.object(board.base,'staged',return_value=(Path('mock.bin'),b'')), \
             patch.object(board,'run_point',side_effect=fail) as run, \
             patch.object(board.base.old.prior,'checkpoint'):
            with self.assertRaisesRegex(RuntimeError,'protection fault'):
                board.execute(row,'mock',Path('mock.json'),b'')
            self.assertEqual(run.call_count,1)
            self.assertTrue(row['final_outputs_off'])
            self.assertFalse(row['automatic_retry'])

    def test_grid_is_fixed_not_current_escalation(self):
        row=board.new_row('mock','run');row['powered_no_alarm']=True
        seen=[]
        def acquire(child,name,source,before,data,rpm,first):
            seen.append((rpm,first))
            child.update(pass_=True,final_capture='mock.bin',
                calibration_point={'passed':0,'rpm':rpm},final_cpu_halted=True,final_outputs_off=True)
        with patch.object(board.base,'staged',return_value=(Path('mock.bin'),b'')), \
             patch.object(board,'run_point',side_effect=acquire), \
             patch.object(board.base.old.prior,'checkpoint'),patch.object(Path,'read_bytes',return_value=b''):
            board.execute(row,'mock',Path('mock.json'),b'')
        self.assertEqual([r for r,_ in seen],list(board.analysis.POINTS)*3)
        self.assertEqual(sum(first for _,first in seen),1)
        self.assertEqual(row['analysis']['fit'],None)

    def test_malformed_completion_cannot_admit_next_point(self):
        for bad in ({},{'DONE':'1','ACTIVE':'1','FRIC':'0'},
                    {'DONE':'1','ACTIVE':'0','FRIC':'1'}):
            with self.assertRaises(RuntimeError):board.validate_finished(bad)
        board.validate_finished({'DONE':'1','ACTIVE':'0','FRIC':'0'})

    def test_exact_pinned_image_and_abi(self):
        self.assertEqual(len(board.image()),212836)
        self.assertEqual(len(board.FIELDS),27)

    def test_real_console_read_whitelist_and_motion_still_denied(self):
        console=object.__new__(board.CalibrationConsole)
        console.request=100;console.port=Mock();console.dispatch=Mock()
        for text in ('MOTOR TEST FF STATUS','MOTOR TEST FRIC STATUS','MOTOR TEST FCAL STATUS'):
            console.read_line=Mock(return_value=f'{console.request+1} OK STATUS')
            self.assertIn(' OK ',console.query(text,.1))
        sent=console.port.write.call_count
        for text in ('MOTOR TEST FCAL RUN POS 40','START','MOTOR TEST FRIC ON','SAVE'):
            with self.assertRaises(ValueError):console.query(text,.1)
        self.assertEqual(console.port.write.call_count,sent)

    def test_restored_baseline_full_identity_before_device_access(self):
        p=subprocess.run([sys.executable,str(ROOT/'tools/friction_calibration_board.py')],
            text=True,capture_output=True,timeout=15)
        self.assertEqual(p.returncode,0,p.stdout+p.stderr)
        r=json.loads(board.RESTORE.read_text('utf-8'))
        self.assertEqual(r['metadata'][2:6],[2,0,0,788])

    @staticmethod
    def good_point():
        return dict(preflight_pass=True,start_attempts=1,motion_ack='7801 OK FCAL QUEUED RPM=40',
            final_cpu_halted=True,final_outputs_off=True,
            outputs=dict(VTOR=0x08008000,SD=0,BDTR=0,CCER=0),
            safe=dict(LATCHED='1',SD='0',MOE='0',FOC='0'),
            current_guard=dict(cl_flags=0,cl_fault_valid=0,adc_fault=0,foc_fault=0,encoder_valid=1),
            snapshot=dict(first_fault=dict(valid=0),cur_confirm=dict(fault=0),
                timing=dict(deadline_miss=0,actual_late_count=0,wall_max_us=32,
                    actual_margin_min_us=12,actual_commit_count=10000)),
            terminal=dict(DONE='1',ACTIVE='0',FRIC='0'),
            calibration_point=dict(finished=1,active=0,passed=1,rpm=40))

    def test_only_isolated_process_no_rotation_can_continue(self):
        row=self.good_point();self.assertEqual(board.classify_point(row),'STEADY')
        row['calibration_point']['passed']=0
        self.assertEqual(board.classify_point(row),'NOT_STEADY')
        row['snapshot']['first_fault']=dict(valid=1,domain=3,fault_reason=7,
            protection_flags=0,encoder_valid=1)
        self.assertEqual(board.classify_point(row),'NO_ROTATION')
        for change in (dict(domain=1),dict(fault_reason=3),dict(protection_flags=1),dict(encoder_valid=0)):
            with patch.dict(row['snapshot']['first_fault'],change):
                with self.assertRaises(RuntimeError):board.classify_point(row)

    def test_new_guard_fault_or_bad_timing_never_hidden_by_old_process_fault(self):
        row=self.good_point();row['calibration_point']['passed']=0
        row['snapshot']['first_fault']=dict(valid=1,domain=3,fault_reason=7,
            protection_flags=0,encoder_valid=1)
        for field in ('cl_flags','cl_fault_valid','adc_fault','foc_fault'):
            with patch.dict(row['current_guard'],{field:1}):
                with self.assertRaises(RuntimeError):board.classify_point(row)
        for field,value in (('deadline_miss',1),('actual_late_count',1),('wall_max_us',51),('actual_margin_min_us',0)):
            with patch.dict(row['snapshot']['timing'],{field:value}):
                with self.assertRaises(RuntimeError):board.classify_point(row)
        with patch.dict(row,{'final_outputs_off':False}):
            with self.assertRaises(RuntimeError):board.classify_point(row)

    def test_real_saved_no_rotation_point_retained_not_retried(self):
        row=board.previous_first_point(ROOT/'tmp/friction-cal-run-1792488721172564400-00.json')
        self.assertEqual(row['point_outcome'],'NO_ROTATION')
        self.assertFalse(row['comparison']['qualified'])
        self.assertAlmostEqual(row['comparison']['net_travel_deg'],145.72265625)

    def test_resume_skips_completed_first_point_but_activates_first_new_point(self):
        row=board.new_row('mock','run');row['powered_no_alarm']=True;seen=[]
        previous=dict(receipt_path='previous.json',calibration_point=dict(rpm=40,passed=0),
                      comparison=dict(rpm=40,outcome='NO_ROTATION'))
        def acquire(child,name,source,before,data,rpm,first):
            seen.append((rpm,first))
            child.update(pass_=True,final_capture='mock.bin',point_outcome='NO_ROTATION',
                calibration_point=dict(rpm=rpm,passed=0),final_cpu_halted=True,final_outputs_off=True)
        with patch.object(board.base,'staged',return_value=(Path('mock.bin'),b'')), \
             patch.object(board,'run_point',side_effect=acquire), \
             patch.object(board.base.old.prior,'checkpoint'),patch.object(Path,'read_bytes',return_value=b''):
            board.execute(row,'mock',Path('mock.json'),b'',previous)
        self.assertEqual(len(seen),23)
        self.assertEqual(seen[0],(80,True))
        self.assertEqual(sum(first for _,first in seen),1)
        self.assertEqual(len(row['calibration_points']),24)
        self.assertTrue(row['acquisition_complete'])

    def test_comparison_keeps_failed_point_and_excludes_ramp_from_plateau(self):
        row=json.loads((ROOT/'tmp/friction-cal-run-1792488721172564400-00.json').read_text('utf-8'))
        result=comparison.summarize(row)
        self.assertEqual(result['outcome'],'NO_ROTATION')
        self.assertFalse(result['qualified'])
        self.assertIsNone(result['candidate_window_mean_iq_a'])
        self.assertGreater(result['sparse_plateau_samples'],0)
        self.assertLess(result['sparse_plateau_speed_mean_rpm'],40)
        self.assertGreater(result['net_travel_deg'],100)

    def test_only_explicit_unstarted_rejection_can_continue(self):
        row=self.good_point();row.pop('motion_ack');row.pop('terminal')
        row['command_rejection']='7801 ERR FCAL NOT_READY'
        row['uart']=[dict(line=row['command_rejection'])]
        row['calibration_point']=dict(rpm=0,used=0,queued=0,active=0,seen=0,valid=0,passed=0)
        self.assertEqual(board.classify_point(row),'NOT_ADMITTED')
        for key in ('used','queued','active','seen','valid'):
            with patch.dict(row['calibration_point'],{key:1}):
                with self.assertRaises(RuntimeError):board.classify_point(row)
        with patch.dict(row,{'command_rejection':'No ACK'}):
            with self.assertRaises(RuntimeError):board.classify_point(row)
        with patch.dict(row['current_guard'],{'foc_fault':1}):
            with self.assertRaises(RuntimeError):board.classify_point(row)

    def test_continue_skips_denied_point_without_resending_trial_or_motion(self):
        previous=[]
        for index in range(17):
            previous.append(dict(receipt_path=f'old{index}.json',rpm=board.analysis.POINTS[index%8],
                point_outcome='NOT_ADMITTED' if index==16 else 'NOT_STEADY',
                calibration_point=dict(rpm=0 if index==16 else board.analysis.POINTS[index%8],passed=0)))
        continuation=dict(rows=previous,source=Path('mock.bin'),before=b'',receipt='partial.json')
        row=board.new_row('mock','run');row['powered_no_alarm']=True;seen=[]
        def acquire(child,name,source,before,data,rpm,first):
            seen.append((rpm,first));child.update(pass_=True,final_capture='mock.bin',
                calibration_point=dict(rpm=rpm,passed=0),final_cpu_halted=True,final_outputs_off=True)
        with patch.object(board.base,'staged') as stage,patch.object(board,'run_point',side_effect=acquire), \
             patch.object(board.base.old.prior,'checkpoint'),patch.object(Path,'read_bytes',return_value=b''):
            board.execute(row,'mock',None,b'',continuation=continuation)
        stage.assert_not_called()
        self.assertEqual(len(seen),7)
        self.assertFalse(any(first for _,first in seen))
        self.assertEqual(len(row['calibration_points']),24)
        self.assertTrue(row['calibration_points'][16]['not_admitted'])
        self.assertEqual(row['calibration_points'][16]['raw_diagnostic_rpm'],0)


if __name__=='__main__':unittest.main()
