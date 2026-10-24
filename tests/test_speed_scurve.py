"""SPEED-only trajectory integration against AW0, no hardware access."""
import hashlib
import json
import re
import subprocess
import unittest
from test_speed_pi_anti_windup import ROOT, GCC, braced
from test_torque_chain import FROZEN, function
from test_torque350_five_second import expanded

BASE='Tightening240rpmAwNoSb3Candidate'
PRESET='Tightening240rpmScurveCandidate'

class SpeedScurveTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.before=expanded('a',BASE); cls.after=expanded('a',PRESET)
        cls.out=ROOT/'tests/speed_scurve_build'; cls.out.mkdir(exist_ok=True)

    def compile_run(self,source,stem):
        for opt in ('-Os','-O2'):
            exe=self.out/(stem+opt+'.exe')
            p=subprocess.run([GCC,'-std=c11',opt,'-Wall','-Wextra','-Werror','-pedantic','-UNDEBUG',
                '-I',str(ROOT/'firmware_common'),'-x','c','-',
                str(ROOT/'firmware_common/speed_scurve.c'),'-o',str(exe)],
                input=source,capture_output=True,text=True)
            self.assertEqual(p.returncode,0,p.stdout+p.stderr)
            p=subprocess.run([str(exe)],capture_output=True,text=True)
            self.assertEqual(p.returncode,0,p.stdout+p.stderr)

    def test_jerk_acceleration_retarget_reverse_reset_and_guard(self):
        self.compile_run((ROOT/'tests/speed_scurve_host.c').read_text(),'generator')

    def test_actual_ramp_owner_speed_only_no_double_ramp(self):
        code='''#include <assert.h>
#include <math.h>
#include "speed_scurve.h"
#define MOTOR_MODE_SPEED 2
'''
        for label,source in (('old',self.before),('sc',self.after)):
            outer=function(source,'FOC_EncoderSpeedUpdate')
            start=outer.index('if (run_speed_pi != 0U)')
            start=outer.index('{',start)+1
            end=outer.index('speed_err =',start)
            code+='''static float run_'''+label+'''(int mode,float target,SpeedScurve *state) {
  float speed_ref_rpm=state->speed_rpm,speed_target_rpm=target,dt_meas=.001f;
  SpeedScurve speed_scurve=*state; (void)mode;
'''+outer[start:end]+'''
  *state=speed_scurve; state->speed_rpm=speed_ref_rpm; return speed_ref_rpm;
}
'''
        code+='''int main(void) {
  SpeedScurve a,b; SpeedScurve_Reset(&a,0); b=a;
  float old=run_old(2,240,&a),sc=run_sc(2,240,&b);
  assert(fabsf(old-.2f)<1e-6f && fabsf(sc-.0005f)<1e-6f);
  for(unsigned k=1;k<1401;++k) run_sc(2,240,&b);
  assert(b.speed_rpm==240 && b.acceleration_rpm_s==0);
  /* The POSITION branch stays bit-for-bit linear, not two serial ramps. */
  for(int sign=-1;sign<=1;sign+=2) {
    SpeedScurve_Reset(&a,0); b=a;
    for(unsigned i=0;i<1600;++i) assert(run_old(1,sign*240,&a)==run_sc(1,sign*240,&b));
  }
  return 0;
}'''
        self.compile_run(code,'actual_owner')

    def test_only_reference_boundary_and_reset_change_no_fast_path_or_pi(self):
        for name in FROZEN+('TighteningTask','SpeedPiAntiWindup_Apply','SpeedBumpless_Apply',
                'MotorControl_SetSpeed','MotorControl_SetIq','MotorControl_SetIdle',
                'Encoder_ElectricalAngleRad','FocFeedbackSafety_Push','FocOcConfirm_Push',
                'FocFp_PushRawSafety','ProtectedLoop_PwmCommitPermit','LatestOriginal_Admit',
                'IntentPort_Config','PowerStage_Disable'):
            old=function(self.before,name); new=function(self.after,name)
            if name=='FOC_EncoderSpeedUpdate':
                start=re.search(r'if \(mode == MOTOR_MODE_SPEED\) \{\s*speed_ref_rpm = SpeedScurve_Step',new).start()
                _,end=braced(new,start)
                legacy_start,legacy_end=braced(new,end)
                new=new[:start]+new[legacy_start+1:legacy_end-1]+new[legacy_end:]
            new=re.sub(r'SpeedScurve_Reset\(&speed_scurve, speed_ref_rpm\);','',new)
            self.assertEqual(re.sub(r'\s+','',old),re.sub(r'\s+','',new),name)
        outer=function(self.after,'FOC_EncoderSpeedUpdate')
        self.assertEqual(outer.count('SpeedScurve_Step('),1)
        self.assertEqual(outer.count('SpeedScurve_Reset('),1)
        reset=function(self.after,'FOC_ResetController')
        self.assertIn('SpeedScurve_Reset(&speed_scurve, speed_ref_rpm);',reset)
        for obj in ('foc_adc_timing_stm32.c.obj','stm32g4xx_it.c.obj'):
            data=[next((ROOT/f'foc2_app_a/build/{p}').rglob(obj)).read_bytes() for p in (BASE,PRESET)]
            self.assertEqual(*data,obj)

    def test_feature_defaults_dependencies_and_identity(self):
        cm=(ROOT/'foc2_app_a/CMakeLists.txt').read_text()
        self.assertRegex(cm,r'option\(FOC_SPEED_SCURVE_CANDIDATE [^\n]+ OFF\)')
        self.assertIn('S-curve requires the separate protected AW0 candidate',cm)
        self.assertNotIn('FOC_SPEED_SCURVE_CANDIDATE',(ROOT/'foc2_app_b/CMakeLists.txt').read_text())
        data=json.loads((ROOT/'foc2_app_a/CMakePresets.json').read_text())
        p=next(p for p in data['configurePresets'] if p['name']==PRESET)
        self.assertEqual(p['inherits'],BASE)
        self.assertEqual(p['cacheVariables'],{'FOC_SPEED_SCURVE_CANDIDATE':'ON'})
        image=(ROOT/f'foc2_app_a/build/{PRESET}/foc2.bin').read_bytes()
        self.assertIn(b'SPEED_CTRL=SC1',image)
        self.assertIn('SpeedPiAntiWindup_Apply',self.after)
        self.assertNotIn('SpeedBrakeTrackResult brake=',function(self.after,'FOC_EncoderSpeedUpdate'))
        self.assertLessEqual(len(image),229376)

    def test_gains_limits_frequencies_and_no_new_main_warnings(self):
        macros=[]; warnings=[]
        for p in (BASE,PRESET):
            base=ROOT/f'foc2_app_a/build/{p}'
            cmd=next(c['command'] for c in json.loads((base/'compile_commands.json').read_text())
                if c['file'].endswith('/Core/Src/main.c'))
            pp=subprocess.run(re.sub(r' -o \S+ -c ',' -E -dM ',cmd),cwd=base,
                capture_output=True,text=True,check=True).stdout
            macros.append(dict(re.findall(r'^#define (\w+) (.*)$',pp,re.M)))
            result=subprocess.run(re.sub(r' -o \S+ -c ',' -fsyntax-only ',cmd),cwd=base,
                capture_output=True,text=True,check=True)
            warnings.append(set(re.findall(r'warning: (.*)',result.stderr)))
        for k,v in macros[0].items():
            if k not in ('__TIME__','__DATE__','__TIMESTAMP__'):
                self.assertEqual(v,macros[1].get(k),k)
        self.assertEqual(set(macros[1])-set(macros[0]),{'FOC_SPEED_SCURVE_CANDIDATE',
            'SPEED_SCURVE_H','SPEED_SCURVE_MAX_ACCEL_RPM_S','SPEED_SCURVE_MAX_JERK_RPM_S2'})
        self.assertFalse(warnings[1]-warnings[0],warnings[1]-warnings[0])
        source=(ROOT/'firmware_common/speed_scurve.c').read_text()
        for token in ('HAL_','TIM1','printf','UART','malloc','integrator','__disable_irq'):
            self.assertNotIn(token,source)

    def test_existing_aw0_l00_and_b_images_preserved(self):
        for path,sha in ((f'foc2_app_a/build/{BASE}/foc2.bin',
                'd3fa11b83686b2b31c551088fdcf2d0a9872fbfd0fb50a52190075a31ecf291a'),
                ('foc2_app_a/build/Tightening240rpmLegacyAwNoSb3Candidate/foc2.bin',
                 'a17b269968b0e58bd7df9f2741ffe7552da5e971d5f9aa8a4f319439798d7324'),
                ('foc2_app_b/build/TighteningCommonModeCandidate/foc2.bin',
                 '7ebdb56408baaa6c213c5dabe236250be673ed5a5c1345dfe64861d1e98dd366')):
            self.assertEqual(hashlib.sha256((ROOT/path).read_bytes()).hexdigest(),sha)

    def test_incompatible_candidate_cmake_rejected_before_build(self):
        for label,flags in (('no_aw',['-DFOC_SPEED_PI_ANTI_WINDUP=OFF']),
                ('with_sb3',['-DFOC_SPEED_SB3_DISABLE_CANDIDATE=OFF']),
                ('legacy',['-DFOC_SPEED_LEGACY_AW_COMPARE=ON'])):
            p=subprocess.run(['cmake','--preset',PRESET,'-B',str(ROOT/'tmp'/('scurve-invalid-'+label)),
                *flags],cwd=ROOT/'foc2_app_a',capture_output=True,text=True)
            self.assertNotEqual(p.returncode,0,p.stdout+p.stderr)
            self.assertIn('S-curve requires the separate protected AW0 candidate',p.stdout+p.stderr)

if __name__=='__main__': unittest.main()
