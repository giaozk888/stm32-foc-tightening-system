from pathlib import Path
import subprocess
import unittest
import test_median_control_integration as binding
ROOT=Path(__file__).resolve().parents[1]
class ProtectionSelftestTests(unittest.TestCase):
    def test_same_c_kernel_on_host_and_locked_profile(self):
        out=ROOT/'tests/foc_current_zero_build/protection_selftest.exe'
        sources=[str(ROOT/'firmware_common/foc_protection_selftest.c'),
                 str(ROOT/'tests/foc_protection_selftest_host.c')]
        for defines in (['-DFOC_PROTECTION_HOST_TEST=1'],
                        ['-DFOC_OC_LAYERED_SELFTEST=1','-DZERO_RETEST_BOOT=1']):
            subprocess.run([binding.GCC,'-std=c11','-O2','-Wall','-Wextra',
                '-Werror','-pedantic','-I',str(ROOT/'firmware_common'),*defines,
                *sources,'-o',str(out)],check=True)
            p=subprocess.run([str(out)],capture_output=True,text=True)
            self.assertEqual(p.returncode,0,p.stdout+p.stderr)
            self.assertIn('CASES=6 CHECKS=36 FAIL=00000000',p.stdout)
    def test_profile_guard_rejects_unlocked_and_zero_macro(self):
        for defines in ([],['-DFOC_OC_LAYERED_SELFTEST=1'],
                        ['-DFOC_OC_LAYERED_SELFTEST=0','-DZERO_RETEST_BOOT=1']):
            p=subprocess.run([binding.GCC,'-std=c11','-fsyntax-only',
                '-I',str(ROOT/'firmware_common'),*defines,
                str(ROOT/'firmware_common/foc_protection_selftest.c')],
                capture_output=True,text=True)
            self.assertNotEqual(p.returncode,0)
    def test_cached_read_only_selftest_not_live_protection(self):
        source=(ROOT/'firmware_common/zero_retest_boot.inc').read_text('utf-8')
        self.assertEqual(source.count('FocProtectionSelftest_Run()'),1)
        self.assertIn('SYNTHETIC_SELFTEST_ONLY_NO_ACQUISITION',source)
        self.assertIn('healthy &= oc_layers_done && !oc_layers_result.failures',source)
        pure=(ROOT/'firmware_common/foc_protection_selftest.c').read_text('utf-8')
        for banned in ('HAL_','malloc(', 'PWM_', 'foc_enable'):
            self.assertNotIn(banned,pure)
if __name__=='__main__': unittest.main()
