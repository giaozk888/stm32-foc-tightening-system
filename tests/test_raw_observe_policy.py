"""Raw-overrange continuation is diagnostic-only and physically hard-off."""

from app_source_view import read_app_source
from pathlib import Path
import subprocess
import unittest
import test_median_control_integration as binding

ROOT=Path(__file__).resolve().parents[1]
GCC=r'D:\Qt\Tools\mingw1310_64\bin\gcc.exe'
REQUIRED=('FOC_RAW_OBSERVE_ONLY','FOC_CURRENT_TREND4','FOC_CURRENT_SPIKE_ONLY',
          'FOC_ISOLATED_CONCURRENCY','FOC_ZERO_MEDIAN_COMPUTE_ONLY')
FORBIDDEN=('ZERO_RETEST_BOOT','FOC_ZERO_FAILURE_TRACE','SWITCH_FEEDBACK_DIAGNOSTIC',
           'FOC_OC_LAYERED_SELFTEST','TIGHTEN_SYNTHETIC_BENCH')

class RawObserveTests(unittest.TestCase):
    def test_actual_policy_keeps_filtered_invalid_and_lock_protection(self):
        binding.MedianControlTests().compile_run('raw_observe_policy',
            ['tests/foc_raw_observe_policy_host.c'],['-D'+x+'=1' for x in REQUIRED])

    def test_filtered_observe_keeps_invalid_and_lock_stop(self):
        binding.MedianControlTests().compile_run('current_observe_policy',
            ['tests/foc_raw_observe_policy_host.c'],
            ['-D'+x+'=1' for x in REQUIRED]+['-DFOC_FILTERED_OBSERVE_ONLY=1'])

    def test_filtered_observe_alone_cannot_compile(self):
        result=subprocess.run([GCC,'-std=c11','-fsyntax-only','-I',str(ROOT/'firmware_common'),
            '-DFOC_FILTERED_OBSERVE_ONLY=1',str(ROOT/'tests/foc_raw_observe_policy_host.c')],
            capture_output=True,text=True)
        self.assertNotEqual(result.returncode,0)
        self.assertIn('restricted to the standalone hard-off',result.stderr)

    def test_compiler_rejects_every_missing_guard_and_forbidden_profile(self):
        source=ROOT/'tests/foc_raw_observe_policy_host.c'
        for missing in REQUIRED:
            result=subprocess.run([GCC,'-std=c11','-fsyntax-only','-I',str(ROOT/'firmware_common'),
                *['-D'+x+'=1' for x in REQUIRED if x!=missing],str(source)],
                capture_output=True,text=True)
            self.assertNotEqual(result.returncode,0,missing)
            self.assertIn('restricted to the standalone hard-off',result.stderr)
        for forbidden in FORBIDDEN:
            result=subprocess.run([GCC,'-std=c11','-fsyntax-only','-I',str(ROOT/'firmware_common'),
                *['-D'+x+'=1' for x in REQUIRED],'-D'+forbidden+'=1',str(source)],
                capture_output=True,text=True)
            self.assertNotEqual(result.returncode,0,forbidden)
            self.assertIn('restricted to the standalone hard-off',result.stderr)

    def test_ab_default_trip_and_opt_in_binding(self):
        for slot in 'ab':
            src=read_app_source(ROOT/f'foc2_app_{slot}/Core/Src/main.c','utf-8')
            start=src.index('static void FOC_CurrentLoopStep(uint16_t u_raw, uint16_t v_raw,\n')
            fn=src[start:src.index('static HAL_StatusTypeDef FOC_EncoderSpeedUpdate(float dt_s)\n{',start)]
            self.assertIn('#else\n        physical_trip ||\n#endif',fn)
            self.assertIn('#if !defined(FOC_RAW_OBSERVE_ONLY)\n    if (physical_trip)',fn)
            self.assertIn('IsolatedBench_Locked()) ||',fn)
            self.assertIn('FocOcShadow_Push(&foc_oc_shadow',fn)
            begin=fn.index('    if (\n#if defined(FOC_CURRENT_TREND4)\n')
            end=fn.index('    {',begin)+len('    {')
            fragment=fn[begin:end]
            for observe,filtered_observe in ((False,False),(True,False),(True,True)):
                flags=['-DFOC_CURRENT_TREND4=1']
                if observe: flags.append('-DFOC_RAW_OBSERVE_ONLY=1')
                if filtered_observe: flags.append('-DFOC_FILTERED_OBSERVE_ONLY=1')
                pp=subprocess.run([GCC,'-E','-P','-x','c',*flags,'-'],input=fragment,
                                  capture_output=True,text=True,check=True).stdout
                self.assertEqual('physical_trip ||' in pp,not observe)
                self.assertEqual('FocRawObserve_StopRequired' in pp,observe)
                for phase in ('iu_A','iv_A','iw_A'):
                    self.assertEqual('fabsf('+phase+') > FOC_CURRENT_TRIP_A' in pp,
                                     not filtered_observe)
            cmake=(ROOT/f'foc2_app_{slot}/CMakeLists.txt').read_text('utf-8')
            self.assertIn('NEVER motor control" OFF)',cmake)
            for guard in REQUIRED[1:]:
                self.assertIn('NOT '+guard,cmake)
            self.assertIn('FOC_RAW_OBSERVE_ONLY=1',cmake)
            self.assertIn('FOC_FILTERED_OBSERVE_ONLY AND NOT FOC_RAW_OBSERVE_ONLY',cmake)
            preset=(ROOT/f'foc2_app_{slot}/CMakePresets.json').read_text('utf-8')
            self.assertNotIn('FOC_RAW_OBSERVE_ONLY',preset)  # opt in only, no changed default
            self.assertNotIn('FOC_FILTERED_OBSERVE_ONLY',preset)

    def test_protocol_has_read_only_explicit_policy(self):
        src=(ROOT/'firmware_common/foc_overcurrent_shadow_protocol.inc').read_text('utf-8')
        self.assertIn('RAW=OBSERVE_POWER_OFF FILTERED=STOP',src)
        self.assertIn('RAW=STOP FILTERED=STOP',src)
        self.assertIn('INVALID=STOP LOCK_LOSS=STOP MOTOR_QUALIFIED=0',src)
        binding.MedianControlTests().compile_run('raw_observe_protocol',
            ['tests/foc_overcurrent_shadow_capture_host.c'],['-D'+x+'=1' for x in REQUIRED])
        binding.MedianControlTests().compile_run('current_observe_protocol',
            ['tests/foc_overcurrent_shadow_capture_host.c'],
            ['-D'+x+'=1' for x in REQUIRED]+['-DFOC_FILTERED_OBSERVE_ONLY=1'])
        self.assertIn('RAW=OBSERVE_POWER_OFF FILTERED=OBSERVE_POWER_OFF',src)

if __name__=='__main__': unittest.main()
