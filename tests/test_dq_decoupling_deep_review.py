"""No device imports/calls: complete saved evidence and actual C quantization."""
import ctypes as ct
import json
import math
from pathlib import Path
import sys
import unittest
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
import dq_decoupling_deep_review as deep


class DeepReviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.native=deep.compile_quantizer(ROOT/'tmp/dq-deep-test-host')
        cls.off=json.loads(deep.OFF.read_text());cls.on=json.loads(deep.ON.read_text())

    def test_both_runs_have_position_change_before_the_late_motion_metric(self):
        for run in (self.off,self.on):
            s=deep.startup_evidence(run)
            self.assertLess(s['first_status_position_ge_0p1deg']['host_elapsed_ms'],160)
            self.assertLess(s['first_status_position_ge_0p1deg']['host_elapsed_ms'],s['existing_start_metric_ms'])
            self.assertGreater(len(s['joined_1khz_source_log_snapshots']),60)
        self.assertEqual(deep.startup_evidence(self.on)['existing_start_metric_ms'],349)

    def test_quantizer_off_identity_and_real_on_below_one_phase_tick(self):
        off=deep.quantization_sensitivity(self.off,self.native,180)
        on=deep.quantization_sensitivity(self.on,self.native,180)
        self.assertEqual(off['any_phase_ccr_changed'],0)
        self.assertEqual(on['planner_rejects'],0)
        self.assertEqual(on['max_phase_delta_ticks'],1)
        self.assertGreater(on['phase_changed_percent'],0)
        self.assertLess(on['phase_changed_percent'],100)
        self.assertEqual(on['kind'],'HOST_COUNTERFACTUAL_NOT_MEASURED_CCR')
        self.assertNotEqual(self.native.quantize(0,0,math.inf,(ct.c_int*6)()),0)

    def test_resolution_and_one_count_PI_voltage_bound_not_accumulated_drift(self):
        s=deep.sensitivity_scales()
        self.assertAlmostEqual(s['single_phase_amp_per_adc_count'],.0067155067,places=10)
        self.assertAlmostEqual(s['command_scale_volts_per_ccr_tick'],.0028235294,places=10)
        self.assertAlmostEqual(s['one_U_offset_count_dq_vector_amplitude_a'],.0077543992,places=10)
        self.assertTrue(.0007<s['one_U_offset_count_single_update_PI_q_bound_v']<.0008)
        self.assertIn('not accumulated drift',s['warning'])

    def test_exact_A_handoff_and_actual_confirmed_B_not_other_B_build_file(self):
        h=deep.handoff()
        self.assertEqual(len(h['images']),4)
        self.assertEqual([r['sign_mode'] for r in h['images']],[0,1,2,3])
        self.assertEqual(h['confirmed_B_payload_bytes'],227964)
        self.assertEqual(h['confirmed_B_payload_sha256'],'1fd1afa9156bb72e71d42a16378d1e0a2cc76d167d9037dd5b3a869d63256826')
        self.assertFalse(h['old_pinned_board_executor_compatible'])
        self.assertTrue(h['no_auto_start'] and h['no_auto_flash'] and h['no_auto_sign_sweep'])


if __name__=='__main__':unittest.main()
