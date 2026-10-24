"""Pure allocation + actual register adapter; all hardware mocked."""
import json
import subprocess
import unittest
from pathlib import Path
from test_torque_chain import GCC
from test_torque_chain import FROZEN,function
from test_torque350_five_second import expanded
import test_pipeline_closed_loop as pipeline

ROOT=Path(__file__).resolve().parents[1]
COMMON=ROOT/'firmware_common'


class CommonModeTests(unittest.TestCase):
    def test_full_geometry_and_exact_differences_Os_O2(self):
        out=ROOT/'tests/common_mode_build'; out.mkdir(exist_ok=True)
        for opt in ('-Os','-O2'):
            exe=out/('planner'+opt+'.exe')
            p=subprocess.run([GCC,'-std=c11',opt,'-Wall','-Wextra','-Werror','-pedantic',
                '-I',str(COMMON),str(COMMON/'foc_adc_window.c'),str(COMMON/'foc_pwm_common_mode.c'),
                str(ROOT/'tests/foc_pwm_common_mode_host.c'),'-o',str(exe)],capture_output=True,text=True)
            self.assertEqual(p.returncode,0,p.stdout+p.stderr)
            p=subprocess.run([str(exe)],capture_output=True,text=True)
            self.assertEqual(p.returncode,0,p.stdout+p.stderr)
            self.assertIn('PASS common-mode',p.stdout)

    def test_actual_prepare_and_existing_commit_admission(self):
        out=ROOT/'tests/common_mode_build'; out.mkdir(exist_ok=True)
        for opt in ('-Os','-O2'):
            exe=out/('adapter'+opt+'.exe')
            p=subprocess.run([GCC,'-std=c11',opt,'-Wall','-Wextra','-Werror','-pedantic','-UNDEBUG',
                '-I',str(ROOT/'tests/foc_preempt_mock'),'-I',str(COMMON),*pipeline.FLAGS,
                '-DFOC_HEAVY_PROFILE_ENABLE=0','-DFOC_PWM_COMMON_MODE_ENABLE=1',
                str(COMMON/'foc_adc_window.c'),str(COMMON/'foc_pwm_common_mode.c'),
                str(COMMON/'foc_adc_raw_buffer.c'),str(COMMON/'foc_adc_timing_stm32.c'),
                str(ROOT/'tests/foc_pwm_common_mode_adapter_host.c'),'-o',str(exe)],capture_output=True,text=True)
            self.assertEqual(p.returncode,0,p.stdout+p.stderr)
            p=subprocess.run([str(exe)],capture_output=True,text=True)
            self.assertEqual(p.returncode,0,p.stdout+p.stderr)
            self.assertIn('plan only, no CCR/gate write',p.stdout)
            original_exe=out/('permit'+opt+'.exe')
            commands=[GCC,'-std=c11',opt,'-Wall','-Wextra','-Werror','-pedantic','-UNDEBUG',
                '-I',str(ROOT/'tests/foc_preempt_mock'),'-I',str(COMMON),*pipeline.FLAGS,
                '-DFOC_HEAVY_PROFILE_ENABLE=0','-DFOC_PWM_COMMON_MODE_ENABLE=1',
                str(COMMON/'foc_adc_window.c'),str(COMMON/'foc_pwm_common_mode.c'),
                str(COMMON/'foc_adc_raw_buffer.c'),str(COMMON/'foc_adc_timing_stm32.c'),
                str(ROOT/'tests/foc_pipeline_power_commit_host.c'),'-o',str(original_exe)]
            p=subprocess.run(commands,capture_output=True,text=True)
            self.assertEqual(p.returncode,0,p.stdout+p.stderr)
            for case in range(10):
                p=subprocess.run([str(original_exe),str(case)],capture_output=True,text=True)
                self.assertEqual(p.returncode,0,(opt,case,p.stdout+p.stderr))

    def test_separate_default_off_candidate(self):
        for slot in 'ab':
            cm=(ROOT/f'foc2_app_{slot}/CMakeLists.txt').read_text()
            self.assertRegex(cm,r'option\(FOC_PWM_COMMON_MODE_ENABLE [^\n]+ OFF\)')
            presets=json.loads((ROOT/f'foc2_app_{slot}/CMakePresets.json').read_text())
            p=next(p for p in presets['configurePresets'] if p['name']=='TighteningCommonModeCandidate')
            self.assertEqual(p['inherits'],'TighteningIntentCandidate')
            self.assertEqual(p['cacheVariables'],{'FOC_PWM_COMMON_MODE_ENABLE':'ON'})

    def test_control_and_pipeline_functions_remain_frozen(self):
        for slot in 'ab':
            baseline=expanded(slot,'TighteningIntentCandidate')
            candidate=expanded(slot,'TighteningCommonModeCandidate')
            for name in FROZEN+('ProtectedLoop_PwmEntry','ProtectedLoop_PwmStage',
                    'ProtectedLoop_PwmCommitPermit','ProtectedLoop_GuardIrqBody',
                    'FocFeedbackSafety_Push','FocOcConfirm_Push','LatestOriginal_Admit',
                    'Encoder_ElectricalAngleRad','MotorControl_SetSpeed','MotorControl_SetIq'):
                self.assertEqual(function(baseline,name),function(candidate,name),name)
            self.assertIn(' CM=85',candidate)
            # Same 192-byte foreground response buffer: complete profile,
            # including QUALIFIED=0, must fit rather than silently truncate.
            import ast,re
            profiles=re.findall(r'snprintf\(out,size,((?:\s*"[^"\n]*"\s*)+)\);',candidate)
            profile=next(p for p in profiles if 'PROTECTED_PIPELINE_CLOSED_LOOP' in p)
            text=''.join(ast.literal_eval(s) for s in re.findall(r'"[^"\n]*"',profile))
            self.assertLess(len(text),192)
            self.assertTrue(text.endswith('QUALIFIED=0'))


if __name__=='__main__': unittest.main()
