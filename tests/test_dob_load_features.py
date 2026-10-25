"""Pure software classifier regressions; no board imports or transports."""
from pathlib import Path
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]
NATIVE = ROOT / 'simulation/dob_simulink/native'
GCC = Path('D:/Qt/Tools/mingw1310_64/bin/gcc.exe')


class LoadFeaturesTests(unittest.TestCase):
    def test_features_at_both_optimization_levels(self):
        for opt in ('-O0', '-O2'):
            exe = ROOT / 'tmp' / ('load-features' + opt + '.exe')
            p = subprocess.run([str(GCC), '-std=c11', opt, '-Wall', '-Wextra', '-Werror',
                                '-I', str(NATIVE), str(NATIVE / 'load_features.c'),
                                str(ROOT / 'tests/load_features_host.c'), '-lm', '-o', str(exe)],
                               capture_output=True, text=True)
            self.assertEqual(p.returncode, 0, p.stderr)
            p = subprocess.run([str(exe)], capture_output=True, text=True)
            self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
            self.assertIn('PASS:', p.stdout)

    def test_has_no_firmware_or_control_dependency(self):
        text = (NATIVE / 'load_features.c').read_text() + (NATIVE / 'load_features.h').read_text()
        for token in ('MotorControl_', 'TIM1', 'HAL_', 'DobFeedback_Update', 'MechanicalDob_Reset'):
            self.assertNotIn(token, text)


if __name__ == '__main__':
    unittest.main()
