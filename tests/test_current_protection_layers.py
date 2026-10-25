"""Three explicit layers, host/hard-off only; no motor qualification."""

from app_source_view import read_app_source
from pathlib import Path
import subprocess
import unittest
import test_median_control_integration as binding
ROOT=Path(__file__).resolve().parents[1]
SOURCE=ROOT/'tests/foc_current_protection_layers_host.c'
OUT=ROOT/'tests/foc_current_zero_build/oc_layers.exe'

class CurrentProtectionLayersTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        OUT.parent.mkdir(exist_ok=True)
        subprocess.run([binding.GCC,'-std=c11','-O2','-Wall','-Wextra','-Werror',
                        '-pedantic','-DFOC_PROTECTION_HOST_TEST=1',
                        '-I',str(ROOT/'firmware_common'),str(SOURCE),'-o',str(OUT)],check=True)

    def run_case(self,case):
        p=subprocess.run([str(OUT),str(case)],capture_output=True,text=True)
        self.assertEqual(p.returncode,0,p.stdout+p.stderr)

    def test_mild_confirmation_and_first_cause(self): self.run_case(0)
    def test_severe_and_hardware_indications(self): self.run_case(1)
    def test_sensing_and_unknown_faults(self): self.run_case(2)
    def test_independent_deadline_including_no_first_sample(self): self.run_case(3)
    def test_strict_mode_and_reject_unconfigured_layered_mode(self): self.run_case(4)
    def test_noise_and_no_filter_clear(self): self.run_case(5)

    def test_compile_guards_forbid_normal_power_profile(self):
        args=[binding.GCC,'-std=c11','-fsyntax-only','-I',str(ROOT/'firmware_common'),str(SOURCE)]
        for defines in ([],['-DFOC_ISOLATED_CONCURRENCY=1'],
                        ['-DFOC_PROTECTION_HOST_TEST=0'],
                        ['-DFOC_ISOLATED_CONCURRENCY=1','-DFOC_ZERO_MEDIAN_COMPUTE_ONLY=0']):
            p=subprocess.run(args+defines,capture_output=True,text=True)
            self.assertNotEqual(p.returncode,0)
            self.assertIn('restricted to host or hard-off fixtures',p.stderr)
        p=subprocess.run(args+['-DFOC_ISOLATED_CONCURRENCY=1',
            '-DFOC_ZERO_MEDIAN_COMPUTE_ONLY=1'],capture_output=True,text=True)
        self.assertEqual(p.returncode,0,p.stderr)
        p=subprocess.run(args+['-DFOC_PROTECTION_HOST_TEST=1','-ffast-math'],
                         capture_output=True,text=True)
        self.assertNotEqual(p.returncode,0)
        self.assertIn('requires finite-value checks',p.stderr)

    def test_no_application_actuation_change(self):
        for slot in 'ab':
            main=read_app_source(ROOT/f'foc2_app_{slot}/Core/Src/main.c','utf-8')
            self.assertNotIn('FocProtection_',main)
            self.assertNotIn('foc_current_protection_layers.h',main)
            self.assertIn('physical_trip ||',main)
        header=(ROOT/'firmware_common/foc_current_protection_layers.h').read_text('utf-8')
        for banned in ('HAL_GPIO_WritePin','PWM_SetDuty(', 'malloc(', 'foc_enable ='):
            self.assertNotIn(banned,header)

if __name__=='__main__': unittest.main()
