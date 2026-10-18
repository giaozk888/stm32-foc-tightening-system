"""Exact APP current-body limit comparison and frozen protection regressions."""
import hashlib
import json
from pathlib import Path
import re
import subprocess
import unittest

ROOT=Path(__file__).resolve().parents[1]
GCC=r'D:\Qt\Tools\mingw1310_64\bin\gcc.exe'


def function(src,name):
    start=re.search(r'\b'+name+r'\([^;{}]*\)\s*\{',src).start()
    brace=src.index('{',start); depth=1; end=brace+1
    while depth:
        depth+=(src[end]=='{')-(src[end]=='}'); end+=1
    return src[start:end]


class VoltageX2Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pp={}; cls.macros={}; cls.out=ROOT/'tests/voltage_x2_build'
        cls.out.mkdir(exist_ok=True)
        for slot in 'ab':
            for preset in ('SpeedBumplessTrial','VoltageX2Trial'):
                base=ROOT/f'foc2_app_{slot}/build/{preset}'
                commands=json.loads((base/'compile_commands.json').read_text())
                cmd=next(c['command'] for c in commands if c['file'].endswith('/Core/Src/main.c'))
                cls.pp[slot,preset]=subprocess.run(re.sub(r' -o \S+ -c ',' -E -P ',cmd),
                    cwd=base,capture_output=True,text=True,check=True).stdout
                cls.macros[slot,preset]=subprocess.run(re.sub(r' -o \S+ -c ',' -E -dM ',cmd),
                    cwd=base,capture_output=True,text=True,check=True).stdout

    def test_only_requested_current_math_constant_changes(self):
        for slot in 'ab':
            old=function(self.pp[slot,'SpeedBumplessTrial'],'FOC_CurrentLoopStep')
            new=function(self.pp[slot,'VoltageX2Trial'],'FOC_CurrentLoopStep')
            self.assertNotEqual(old,new)
            self.assertEqual(old.replace('0.80f','1.60f'),new)

    def test_all_other_control_protection_pipeline_kernels_identical(self):
        for slot in 'ab':
            for name in ('FOC_EncoderSpeedUpdate','TighteningTask','ProtectedLoop_PwmEntry',
                'ProtectedLoop_PwmStage','ProtectedLoop_Pair','ProtectedLoop_AdcIrq',
                'FocCurrentValidation_Push','FocFp_Poll'):
                self.assertEqual(function(self.pp[slot,'SpeedBumplessTrial'],name),
                                 function(self.pp[slot,'VoltageX2Trial'],name),name)

    def test_constants_integrator_gains_and_frequency_unchanged(self):
        fixed=('FOC_INTEGRATOR_LIMIT_V','FOC_CURRENT_KP_V_PER_A','FOC_CURRENT_KI_V_PER_AS',
               'FOC_TS_S','PWM_ARR','CURRENT_GAIN_MV_PER_A','FOC_CURRENT_TRIP_A',
               'CUR_CONFIRM_CLEAR_GOOD_SAMPLES','CUR_CONFIRM_MAX_CYCLES',
               'ELECTRICAL_ZERO_RAW','POLE_PAIRS','ENCODER_DIRECTION')
        for slot in 'ab':
            for name in fixed:
                pattern=r'^#define '+name+r' .*$'
                old=re.search(pattern,self.macros[slot,'SpeedBumplessTrial'],re.M)
                new=re.search(pattern,self.macros[slot,'VoltageX2Trial'],re.M)
                self.assertIsNotNone(old,name); self.assertEqual(old.group(0),new.group(0))
            self.assertIn('#define FOC_VOLTAGE_LIMIT_V 1.60f',self.macros[slot,'VoltageX2Trial'])

    def test_real_commit_object_identical_and_no_new_source_warnings(self):
        for slot in 'ab':
            root=ROOT/f'foc2_app_{slot}/build'; objects=[]; warnings={}
            for preset in ('SpeedBumplessTrial','VoltageX2Trial'):
                base=root/preset
                files=list(base.rglob('foc_adc_timing_stm32.c.obj'))
                self.assertEqual(len(files),1)
                objects.append(files[0].read_bytes())
                commands=json.loads((base/'compile_commands.json').read_text())
                cmd=next(c['command'] for c in commands if c['file'].endswith('/Core/Src/main.c'))
                p=subprocess.run(re.sub(r' -o \S+ -c ',' -fsyntax-only ',cmd),
                    cwd=base,capture_output=True,text=True,check=True)
                warnings[preset]=set(re.findall(r'warning: (.*)',p.stderr))
            self.assertEqual(objects[0],objects[1])
            self.assertFalse(warnings['VoltageX2Trial']-warnings['SpeedBumplessTrial'])

    def test_actual_ab_current_body_at_both_limits(self):
        names=('TWO_PI_F','ADC_VREF_MV','ADC_FULL_SCALE','CURRENT_GAIN_MV_PER_A',
               'FOC_TS_S','FOC_CURRENT_KP_V_PER_A','FOC_CURRENT_KI_V_PER_AS',
               'FOC_DC_BUS_V','FOC_VOLTAGE_LIMIT_V','FOC_INTEGRATOR_LIMIT_V')
        for slot in 'ab':
            text=(ROOT/f'foc2_app_{slot}/Core/Src/main.c').read_text()
            begin=text.index('static void FOC_CurrentLoopStep(uint16_t u_raw, uint16_t v_raw,\n')
            end=text.index('\n\n/*\n * Update AS5047P,',begin)
            (self.out/'voltage_x2_current_body.inc').write_text(text[begin:end])
            for preset in ('SpeedBumplessTrial','VoltageX2Trial'):
                constants='\n'.join(re.search(r'^#define '+n+r' .+$',self.macros[slot,preset],re.M).group(0) for n in names)
                (self.out/'voltage_x2_constants.inc').write_text(constants+'\n')
                exe=self.out/f'{slot}-{preset}.exe'
                subprocess.run([GCC,'-std=c11','-O2','-Wall','-Wextra','-Werror','-pedantic',
                    '-I',str(self.out),str(ROOT/'tests/voltage_x2_current_host.c'),'-o',str(exe)],check=True)
                for case in range(5):
                    subprocess.run([str(exe),str(case)],capture_output=True,text=True,check=True)

    def test_new_images_separate_old_sb2_unchanged(self):
        pins={'a':'b78864f64ff417d4cfc3101f9d6f22292a96e89807359f4154aa8ee6ba0f8488',
              'b':'99e15d9e25c0aeade7dd57617dcd394dd007f1cbc05c652719ab7f63be1eba18'}
        for slot in 'ab':
            root=ROOT/f'foc2_app_{slot}/build'
            self.assertEqual(hashlib.sha256((root/'SpeedBumplessTrial/foc2.bin').read_bytes()).hexdigest(),pins[slot])
            new=(root/'VoltageX2Trial/foc2.bin').read_bytes()
            self.assertLessEqual(len(new),229376)
            self.assertIn(b'VLIMIT_MV=1600 ILIMIT_MV=750',new)
            self.assertIn(b'TRIP_MA=4000',new)


if __name__=='__main__': unittest.main()
