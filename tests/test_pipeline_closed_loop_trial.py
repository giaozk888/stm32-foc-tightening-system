"""No hardware: candidate trial CLI and exact READY/actual-commit gates."""
import copy
import sys
import struct
import unittest
from types import SimpleNamespace
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
import pipeline_closed_loop_trial as trial
import pipeline_closed_loop_restore as restore


def good():
    return dict(profile=trial.fields('OK '+trial.candidate.MARKER.decode()),
        state=dict(STATE='1',USED='0',QUEUED='0',ARMED='1',ZERO='3',
            SD='0',MOE='0',CCER='0',FLAGS='0',FAULT='0',QUALIFIED='0'),
        timing=dict(CLOCK_HZ='1000000',LATE='0',MAX_US='35',WORK='2000',OUTER='200',
            IRQ='2000',LEASE_US='400000',SAMPLE_US='100',OUTER_US='2000'),
        fw=dict(CURRENT='A',CONFIRMED='A',PENDING='-',ATTEMPTS='0',ACTIVE='0'),
        zero=dict(STATE='3',REASON='0'),adc=dict(DWT='1',MISS='0',PF='0',PAIRS='2000'),
        commit=dict(RC='1',READY='1',FAIL='0',GUARD='170',BOTTOM_LATE='8'),
        fault=dict(VALID='0'),status=dict(MODE='IDLE',BUSY='0',FLT='0'),
        health=dict(READY='1',MASK='0x000'),safe=dict(LATCHED='0'))


class TrialTests(unittest.TestCase):
    def test_current_actual_gate_not_old_hypothetical_tail(self):
        trial.validate_ready(good())

    def test_actual_commit_not_ready_rejected(self):
        for key,value in (('READY','0'),('FAIL','1'),('GUARD','0')):
            row=good(); row['commit'][key]=value
            with self.assertRaises(RuntimeError):
                trial.validate_ready(row)

    def test_fault_or_output_enabled_rejected(self):
        for group,key in (('state','SD'),('state','MOE'),('state','FAULT'),('fault','VALID'),
                          ('status','FLT'),('adc','MISS'),('adc','PF'),('safe','LATCHED')):
            row=good(); row[group][key]='1'
            with self.assertRaises(RuntimeError):
                trial.validate_ready(row)

    def test_wrong_profile_or_unconfirmed_rejected(self):
        for group,key,value in (('profile','HARD_OFF','1'),('profile','PIPELINE','0'),
                                ('fw','CONFIRMED','B'),('fw','PENDING','A')):
            row=good(); row[group][key]=value
            with self.assertRaises(RuntimeError):
                trial.validate_ready(row)

    def test_no_timing_or_deadline_gate_relaxation(self):
        for key,value in (('LATE','1'),('MAX_US','51'),('SAMPLE_US','200')):
            row=good(); row['timing'][key]=value
            with self.assertRaises(RuntimeError):
                trial.validate_ready(row)

    def test_console_rejects_motion_confirmation_and_fault_clear(self):
        console=trial.Console(None)
        for command in ('START','MOTOR TEST SPEED','FW END','FAULT CLEAR','RESET'):
            with self.assertRaises(ValueError):
                console.query(command)

    def test_default_no_device_or_private_access(self):
        with patch.object(sys,'argv',['trial']),patch.object(trial,'run_trial') as run, \
                patch.object(trial,'load_stage') as load:
            self.assertEqual(trial.main(),0)
            run.assert_not_called(); load.assert_not_called()

    def test_physical_gate_before_device_access(self):
        for argv in (['trial','--execute-single-trial'],['trial','--allow-one-original-start']):
            with patch.object(sys,'argv',argv),patch.object(trial,'run_trial') as run:
                with self.assertRaises(SystemExit):
                    trial.main()
                run.assert_not_called()

    def test_light_counter_schema_not_heavy_zero_fields(self):
        symbols=trial.schema.symbols(trial.candidate.ELF)
        ram=bytearray(0x20000)
        flash=bytearray(0x80000)
        data=trial.candidate.image()
        flash[0x8000:0x8000+len(data)]=data
        def put(name,offset,value):
            struct.pack_into('<I',ram,symbols[name][0]-0x20000000+offset,value)
        put('foc_preempt_timing',8,4904)
        put('foc_pwm_write_profile',0,1234)
        put('foc_pwm_write_profile',20,2036)
        row=dict(pass_=True,ram_backup='ram',final_backup='flash',snapshot_vtor=0x08008000)
        with patch.object(trial.candidate.tx.prior,'private_path',
                side_effect=lambda p: SimpleNamespace(read_bytes=lambda: ram if p=='ram' else flash)):
            trial.decode(row,data)
        self.assertTrue(row['timing_pass'])
        self.assertIsNone(row['measured']['timing']['frames'])
        self.assertEqual(row['measured']['actual_ccr']['actual_commit_count'],1234)
        self.assertNotIn('actual_ccr_writes',row['measured']['actual_ccr'])

    def test_restore_default_and_power_gate(self):
        with patch.object(sys,'argv',['restore']),patch.object(restore,'debug') as debug:
            self.assertEqual(restore.main(),0)
            debug.assert_not_called()
        with patch.object(sys,'argv',['restore','--restore-preserved-b']), \
                patch.object(restore,'debug') as debug:
            with self.assertRaises(SystemExit):
                restore.main()
            debug.assert_not_called()

    def test_restore_requires_exact_stopped_trial(self):
        row=dict(mode='trial',image_sha256=trial.candidate.SHA,elf_sha256=trial.candidate.ELF_SHA,
            snapshot_vtor=0x08008000,trial_requests=1,original_start_runner_invocations=1,
            activation_submitted=True,final_cpu_halted=True,final_outputs_off=True,
            all_app_and_private_bytes_unchanged=True)
        restore.stopped_trial(row)
        for key in ('final_outputs_off','final_cpu_halted','all_app_and_private_bytes_unchanged'):
            bad=copy.deepcopy(row); bad[key]=False
            with self.assertRaises(ValueError):
                restore.stopped_trial(bad)


if __name__ == '__main__':
    unittest.main()
