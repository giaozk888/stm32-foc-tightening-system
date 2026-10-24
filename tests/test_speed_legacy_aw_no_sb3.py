"""Remove only new AW1; preserve the historical PI and all protection."""
import hashlib
import json
import re
import subprocess
import unittest
import test_speed_pi_anti_windup as awtest
from test_speed_pi_anti_windup import ROOT,GCC,braced
from test_torque_chain import FROZEN,function
from test_torque350_five_second import expanded

BASE='Tightening240rpmAwNoSb3Candidate'
PRESET='Tightening240rpmLegacyAwNoSb3Candidate'


class LegacyAwTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.before=expanded('a',BASE); cls.after=expanded('a',PRESET)
        cls.out=ROOT/'tests/speed_pi_anti_windup_build'; cls.out.mkdir(exist_ok=True)

    def test_only_new_aw_branch_removed_all_other_control_unchanged(self):
        for name in FROZEN+('TighteningTask','SpeedBumpless_Apply',
                'MotorControl_SetSpeed','MotorControl_SetIq','Encoder_ElectricalAngleRad',
                'FocFeedbackSafety_Push','FocOcConfirm_Push','FocFp_PushRawSafety',
                'ProtectedLoop_PwmCommitPermit','LatestOriginal_Admit','IntentPort_Config'):
            old=function(self.before,name); new=function(self.after,name)
            if name=='FOC_EncoderSpeedUpdate':
                start=re.search(r'if \(mode == MOTOR_MODE_SPEED\) \{\s*SpeedPiAntiWindupResult aw=',old).start()
                _,end=braced(old,start); legacy_start,legacy_end=braced(old,end)
                old=old[:start]+old[legacy_start+1:legacy_end-1]+old[legacy_end:]
                self.assertNotIn('SpeedPiAntiWindup_Apply',new)
                self.assertNotIn('SpeedBrakeTrack_Apply',new)
                self.assertIn('speed_integrator_A = i_candidate',new)
                self.assertIn('fabsf(encoder_speed_rpm) > 300.0f',new)
                self.assertEqual(new.count('foc_iq_ref_A = iq_cmd;'),1)
            self.assertEqual(re.sub(r'\s+','',old),re.sub(r'\s+','',new),name)
        for obj in ('foc_adc_timing_stm32.c.obj','stm32g4xx_it.c.obj'):
            values=[next((ROOT/f'foc2_app_a/build/{p}').rglob(obj)).read_bytes() for p in (BASE,PRESET)]
            self.assertEqual(*values,obj)

    def test_real_pi_command_and_integral_comparison_at_os_o2(self):
        code='''#include <assert.h>
#include <math.h>
#include "speed_pi_anti_windup.h"
#define MOTOR_MODE_SPEED 2
static float ClampFloat(float v,float lo,float hi) { return v<lo?lo:v>hi?hi:v; }
'''
        for name,source in (('aw',self.before),('legacy',self.after)):
            outer=function(source,'FOC_EncoderSpeedUpdate')
            start=re.search(r'i_candidate\s*=\s*ClampFloat\(i_candidate',outer).start()
            end=outer.index('foc_iq_ref_A = iq_cmd;',start)+len('foc_iq_ref_A = iq_cmd;')
            code+='''static void run_'''+name+'''(float previous,float candidate,float p,float error,int mode,
    float *integral,float *current) {
    float speed_integrator_A=previous,sb2_previous_A=previous,i_candidate=candidate;
    float p_term=p,speed_err=error,speed_iq_limit_A=.5f,iq_unsat=0,iq_cmd=0,foc_iq_ref_A=0;
    unsigned speed_integrator_bleed_active=0,speed_overspeed_bleed_active=0;
    (void)sb2_previous_A; (void)mode;
'''+outer[start:end]+'''
    *integral=speed_integrator_A; *current=foc_iq_ref_A;
}
'''
        code+='''int main(void) {
  for(int sign=-1;sign<=1;sign+=2) {
    float s=(float)sign,ai,ac,li,lc;
    run_aw(s*.29f,s*.31f,s*.2f,s*20,2,&ai,&ac);
    run_legacy(s*.29f,s*.31f,s*.2f,s*20,2,&li,&lc);
    assert(fabsf(ai-s*.30f)<1e-6f && fabsf(li-s*.29f)<1e-6f);
    assert(fabsf(ac-s*.5f)<1e-6f && ac==lc);
    run_aw(s*.1f,s*.11f,s*.03f,s*10,2,&ai,&ac);
    run_legacy(s*.1f,s*.11f,s*.03f,s*10,2,&li,&lc);
    assert(ai==li && ac==lc); /* unsaturated unchanged */
    run_aw(s*.29f,s*.31f,s*.2f,s*20,1,&ai,&ac);
    run_legacy(s*.29f,s*.31f,s*.2f,s*20,1,&li,&lc);
    assert(ai==li && ac==lc); /* POSITION unchanged */
    run_legacy(s*.34f,s*.35f,s*.3f,s*100,2,&li,&lc);
    assert(fabsf(li-s*.34f)<1e-6f && fabsf(lc-s*.5f)<1e-6f); /* historical conditional integration */
    run_legacy(0,s*.5f,0,s*20,2,&li,&lc);
    assert(fabsf(li-s*.35f)<1e-6f); /* original integral cap */
  }
  return 0;
}'''
        awtest.SpeedAntiWindupTests.compile_run(self,code,'actual_legacy_aw')

    def test_macros_profile_and_warning_delta(self):
        macros=[]; warnings=[]
        for preset in (BASE,PRESET):
            base=ROOT/f'foc2_app_a/build/{preset}'
            cmd=next(c['command'] for c in json.loads((base/'compile_commands.json').read_text())
                if c['file'].endswith('/Core/Src/main.c'))
            result=subprocess.run(re.sub(r' -o \S+ -c ',' -E -dM ',cmd),cwd=base,
                capture_output=True,text=True,check=True)
            macros.append(dict(re.findall(r'^#define (\w+) (.*)$',result.stdout,re.M)))
            check=subprocess.run(re.sub(r' -o \S+ -c ',' -fsyntax-only ',cmd),cwd=base,
                capture_output=True,text=True,check=True)
            warnings.append(set(re.findall(r'warning: (.*)',check.stderr)))
        removed={'FOC_SPEED_PI_ANTI_WINDUP','SPEED_PI_ANTI_WINDUP_H'}
        self.assertEqual(set(macros[0])-set(macros[1]),removed)
        self.assertEqual(set(macros[1])-set(macros[0]),{'FOC_SPEED_LEGACY_AW_COMPARE'})
        for name,value in macros[0].items():
            if name not in removed|{'__TIME__','__DATE__','__TIMESTAMP__'}:
                self.assertEqual(value,macros[1].get(name),name)
        self.assertFalse(warnings[1]-warnings[0])
        data=(ROOT/f'foc2_app_a/build/{PRESET}/foc2.bin').read_bytes()
        self.assertIn(b'SPEED_CTRL=L00',data); self.assertIn(b'TRIP_MA=4000',data)
        self.assertLessEqual(len(data),229376)

    def test_old_candidates_and_b_preserved_default_off(self):
        cm=(ROOT/'foc2_app_a/CMakeLists.txt').read_text()
        self.assertRegex(cm,r'option\(FOC_SPEED_LEGACY_AW_COMPARE [^\n]+ OFF\)')
        self.assertNotIn('FOC_SPEED_LEGACY_AW_COMPARE',(ROOT/'foc2_app_b/CMakeLists.txt').read_text())
        for path,sha in ((f'foc2_app_a/build/{BASE}/foc2.bin',
                'd3fa11b83686b2b31c551088fdcf2d0a9872fbfd0fb50a52190075a31ecf291a'),
                ('foc2_app_b/build/TighteningCommonModeCandidate/foc2.bin',
                 '7ebdb56408baaa6c213c5dabe236250be673ed5a5c1345dfe64861d1e98dd366')):
            self.assertEqual(hashlib.sha256((ROOT/path).read_bytes()).hexdigest(),sha)
        presets=json.loads((ROOT/'foc2_app_a/CMakePresets.json').read_text())
        preset=next(p for p in presets['configurePresets'] if p['name']==PRESET)
        self.assertEqual(preset['inherits'],BASE)
        self.assertEqual(preset['cacheVariables'],
            {'FOC_SPEED_PI_ANTI_WINDUP':'OFF','FOC_SPEED_LEGACY_AW_COMPARE':'ON'})


if __name__=='__main__': unittest.main()
