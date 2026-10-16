"""Hardware-backed design candidate only; never a motor protection qualification."""
from pathlib import Path
import subprocess
import unittest
import test_median_control_integration as binding
ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT/'tests/foc_filtered_protection_candidate_host.c'
OUT = ROOT/'tests/foc_current_zero_build/filtered_protection_candidate.exe'

class FilteredProtectionCandidateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        OUT.parent.mkdir(exist_ok=True)
        subprocess.run([binding.GCC, '-std=c11', '-O2', '-Wall', '-Wextra', '-Werror',
                        '-pedantic', '-DFOC_PROTECTION_HOST_TEST=1',
                        '-I', str(ROOT/'firmware_common'), str(SOURCE), '-o', str(OUT)], check=True)

    def run_case(self, n):
        p = subprocess.run([str(OUT), str(n)], capture_output=True, text=True)
        self.assertEqual(p.returncode, 0, p.stdout+p.stderr)

    def test_raw_amplitude_is_not_a_trip_and_single_resolves(self): self.run_case(0)
    def test_filtered_confirmation_reconstruction_and_sticky_fault(self): self.run_case(1)
    def test_hardware_health_and_invalid_values(self): self.run_case(2)
    def test_deadlines_sequence_delay_warmup_and_wrap(self): self.run_case(3)
    def test_repair_budget_and_counter_saturation(self): self.run_case(4)
    def test_config_rejection(self): self.run_case(5)
    def test_exhaustive_confirmation_patterns(self): self.run_case(6)
    def test_doubled_window_budget_six_allowed_seventh_latches(self): self.run_case(7)
    def test_doubled_streak_four_allowed_fifth_latches_and_expiry(self): self.run_case(8)

    def test_compile_guards_and_unchanged_motor_applications(self):
        args = [binding.GCC, '-std=c11', '-fsyntax-only', '-I', str(ROOT/'firmware_common'), str(SOURCE)]
        for defines in ([], ['-DFOC_PROTECTION_HOST_TEST=0'],
                        ['-DFOC_ISOLATED_CONCURRENCY=1'],
                        ['-DFOC_ISOLATED_CONCURRENCY=1', '-DFOC_ZERO_MEDIAN_COMPUTE_ONLY=0']):
            p = subprocess.run(args+defines, capture_output=True, text=True)
            self.assertNotEqual(p.returncode, 0)
            self.assertIn('requires an explicitly isolated fixture', p.stderr)
        p = subprocess.run(args+['-DFOC_ISOLATED_CONCURRENCY=1', '-DFOC_ZERO_MEDIAN_COMPUTE_ONLY=1'],
                           capture_output=True, text=True)
        self.assertEqual(p.returncode, 0, p.stderr)
        bridge=['-DSWITCH_FILTERED_BRIDGE_DIAGNOSTIC=1','-DSWITCH_FEEDBACK_DIAGNOSTIC=1',
                '-DZERO_RETEST_BOOT=1','-DZERO_MEDIAN_DIAGNOSTIC=1']
        for defines in (bridge[:-1],bridge+['-DSWITCH_SIGNAL_ONLY_DIAGNOSTIC=1']):
            p=subprocess.run(args+defines,capture_output=True,text=True)
            self.assertNotEqual(p.returncode,0)
        p=subprocess.run(args+bridge,capture_output=True,text=True)
        self.assertEqual(p.returncode,0,p.stderr)
        p = subprocess.run(args+['-DFOC_PROTECTION_HOST_TEST=1', '-ffast-math'],
                           capture_output=True, text=True)
        self.assertNotEqual(p.returncode, 0)
        self.assertIn('requires finite-value checks', p.stderr)
        for slot in 'ab':
            src = (ROOT/f'foc2_app_{slot}/Core/Src/main.c').read_text('utf-8')
            self.assertNotIn('FocFp_', src)
            self.assertNotIn('foc_filtered_protection_candidate.h', src)
            self.assertIn('physical_trip ||', src)

if __name__ == '__main__': unittest.main()
