"""A-only overspeed setting; files/compiler only, never device access."""
import hashlib
import json
from pathlib import Path
import re
import subprocess
import unittest
from test_torque_chain import ROOT, GCC, function
from test_torque350_five_second import expanded
from test_rundown240_candidate import BASE_FLAGS, CANDIDATE_FLAGS


class PsiTrip500Tests(unittest.TestCase):
    def test_compiled_threshold_boundary_and_default_preserved(self):
        # Use the real shared threshold header, not a duplicated test constant.
        for raised, trip in ((False, 300), (True, 500)):
            code = '''#include <assert.h>
#include <math.h>
#include <string.h>
#include "foc_rundown240_candidate.h"
int main(void) {
 assert(FOC_RUNDOWN240_TRIP_RPM == EXPECTED);
 assert(!strcmp(FOC_RUNDOWN240_TRIP_TEXT, EXPECTED_TEXT));
 const float speed[] = {-501,-500,-499,0,499,500,501};
 for (unsigned i=0;i<7;++i)
  assert((fabsf(speed[i]) > FOC_RUNDOWN240_TRIP_RPM) ==
         (fabsf(speed[i]) > EXPECTED));
 assert(FOC_RUNDOWN240_IQ_LIMIT_A == .50f);
 return 0;
}'''
            flags = BASE_FLAGS + CANDIDATE_FLAGS
            if raised:
                flags += ['-DFOC_PSI_IDENT_DIAG=1', '-DFOC_PSI_IDENT_TRIP500=1']
            exe = ROOT / f'tmp/psi-trip-{trip}.exe'
            p = subprocess.run([GCC, '-std=c11', '-O2', '-Wall', '-Wextra', '-Werror',
                '-I', str(ROOT/'firmware_common'), *flags, f'-DEXPECTED={trip}',
                f'-DEXPECTED_TEXT="{trip}"', '-x', 'c', '-', '-o', str(exe)],
                input=code, text=True, capture_output=True)
            self.assertEqual(p.returncode, 0, p.stdout+p.stderr)
            p = subprocess.run([str(exe)], text=True, capture_output=True)
            self.assertEqual(p.returncode, 0, p.stdout+p.stderr)

    def test_trip_option_rejected_outside_exclusive_diagnostic(self):
        for flags in ([], BASE_FLAGS+CANDIDATE_FLAGS):
            p = subprocess.run([GCC, '-std=c11', '-I', str(ROOT/'firmware_common'),
                *flags, '-DFOC_PSI_IDENT_TRIP500=1', '-fsyntax-only', '-x', 'c', '-'],
                input='#include "foc_rundown240_candidate.h"\n', text=True, capture_output=True)
            self.assertNotEqual(p.returncode, 0)
            self.assertIn('500rpm trip requires', p.stderr)

    def test_real_both_guards_and_unchanged_command_cap(self):
        old = expanded('a', 'PsiKeIdentificationDiagnostic')
        new = expanded('a', 'PsiKe500rpmTripDiagnostic')
        self.assertIn('CL_OVERSPEED_RPM=500U', new)
        self.assertIn('CL_OVERSPEED_RPM=300U', old)
        outer_old = function(old, 'FOC_EncoderSpeedUpdate')
        outer_new = function(new, 'FOC_EncoderSpeedUpdate')
        self.assertEqual(outer_new.count('((float)500U)'), 1)
        self.assertEqual(outer_old, outer_new.replace('((float)500U)', '300.0f'))
        for name in ('FOC_CurrentLoopStep', 'FOC_ResetController',
                     'ProtectedLoop_PwmEntry', 'ProtectedLoop_SetDuty',
                     'ProtectedLoop_GuardIrqBody', 'ProtectedLoop_AdcIrq',
                     'MotorControl_SetSpeed', 'PowerStage_Enable', 'PowerStage_Disable',
                     'Encoder_ElectricalAngleRad', 'PsiIdent_Command', 'TighteningTask'):
            self.assertEqual(function(old, name), function(new, name), name)
        self.assertIn('-250.0f', function(new, 'MotorControl_SetSpeed'))
        self.assertIn('"500" "rpm SAVE=OFF;', new)

    def test_a_only_default_off_and_no_board_runner_repin(self):
        option = 'FOC_PSI_IDENT_TRIP500'
        cm = (ROOT/'foc2_app_a/CMakeLists.txt').read_text()
        self.assertRegex(cm, r'option\('+option+r' [^\n]+ OFF\)')
        for f in ('CMakeLists.txt', 'CMakePresets.json', 'Core/Src/main.c'):
            self.assertNotIn(option, (ROOT/'foc2_app_b'/f).read_text())
        presets = json.loads((ROOT/'foc2_app_a/CMakePresets.json').read_text())
        p = next(p for p in presets['configurePresets'] if p['name']=='PsiKe500rpmTripDiagnostic')
        self.assertEqual(p['cacheVariables'], {option:'ON'})
        old_image = ROOT/'foc2_app_a/build/PsiKeIdentificationDiagnostic/foc2.bin'
        self.assertEqual(hashlib.sha256(old_image.read_bytes()).hexdigest(),
            'a260cc660b1c6bedaf8bc098c31e53505fd1c7fdd11595a9a1b95d985d186859')
        self.assertNotEqual(old_image.read_bytes(),
            (ROOT/'foc2_app_a/build/PsiKe500rpmTripDiagnostic/foc2.bin').read_bytes())


if __name__ == '__main__':
    unittest.main()
