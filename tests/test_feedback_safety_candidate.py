"""Actual C pipeline tests; no device access, firmware upload or power control."""
from pathlib import Path
import subprocess
import unittest
import test_median_control_integration as binding

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'tests/foc_feedback_safety_candidate_host.c'
OUT = ROOT / 'tests/foc_current_zero_build/feedback_safety_candidate.exe'
FILTER = ['-DFOC_CURRENT_TREND4=1', '-DFOC_CURRENT_SPIKE_ONLY=1']

class FeedbackSafetyCandidateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        OUT.parent.mkdir(exist_ok=True)
        subprocess.run([binding.GCC, '-std=c11', '-O2', '-Wall', '-Wextra', '-Werror',
                        '-pedantic', '-UNDEBUG', '-DFOC_PROTECTION_HOST_TEST=1', *FILTER,
                        '-I', str(ROOT / 'firmware_common'), str(SOURCE), '-o', str(OUT)], check=True)

    def run_case(self, n):
        p = subprocess.run([str(OUT), str(n)], capture_output=True, text=True)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)

    def test_actual_filter_frame_angle_time_alignment_and_single_consumption(self): self.run_case(0)
    def test_spike_repair_and_sustained_filtered_current_confirmation(self): self.run_case(1)
    def test_hardware_health_lock_loss_and_invalid_input(self): self.run_case(2)
    def test_timeout_sequence_and_wrap(self): self.run_case(3)
    def test_actual_repair_quality_budget(self): self.run_case(4)
    def test_calibration_mapping_rejected_when_invalid(self): self.run_case(5)

    def test_build_boundaries_and_unchanged_live_bindings(self):
        args = [binding.GCC, '-std=c11', '-fsyntax-only', '-I', str(ROOT / 'firmware_common'), str(SOURCE)]
        valid = ['-DFOC_PROTECTION_HOST_TEST=1', *FILTER]
        invalid = [FILTER, ['-DFOC_PROTECTION_HOST_TEST=1'],
                   ['-DFOC_PROTECTION_HOST_TEST=1', '-DFOC_CURRENT_TREND4=0', FILTER[1]],
                   [*valid, '-DSWITCH_FEEDBACK_DIAGNOSTIC=1'], [*valid, '-ffast-math']]
        for defines in invalid:
            with self.subTest(defines=defines):
                p = subprocess.run(args + defines, capture_output=True, text=True)
                self.assertNotEqual(p.returncode, 0, p.stderr)
        hard_off = ['-DFOC_ISOLATED_CONCURRENCY=1', '-DFOC_ZERO_MEDIAN_COMPUTE_ONLY=1', *FILTER]
        p = subprocess.run(args + hard_off, capture_output=True, text=True)
        self.assertEqual(p.returncode, 0, p.stderr)
        for slot in 'ab':
            src = (ROOT / f'foc2_app_{slot}/Core/Src/main.c').read_text('utf-8')
            self.assertNotIn('FocFeedbackSafety_', src)
            self.assertNotIn('foc_feedback_safety_candidate.h', src)
            self.assertIn('physical_trip ||', src)

if __name__ == '__main__': unittest.main()
