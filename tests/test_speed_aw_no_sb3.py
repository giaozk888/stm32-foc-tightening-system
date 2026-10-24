"""AW1 vs AW0: only SB3 fast ceiling omitted, no protection removal."""
import hashlib
import json
import re
import subprocess
import unittest
import test_speed_pi_anti_windup as awtest
from test_speed_pi_anti_windup import ROOT,GCC,braced
from test_torque_chain import FROZEN,function
from test_torque350_five_second import expanded

BASE='Tightening240rpmSpeedAntiWindupCandidate'
PRESET='Tightening240rpmAwNoSb3Candidate'


class NoSb3Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.before=expanded('a',BASE); cls.after=expanded('a',PRESET)
        cls.out=ROOT/'tests/speed_pi_anti_windup_build'; cls.out.mkdir(exist_ok=True)

    def test_only_brake_apply_removed_outer_pi_and_all_safety_unchanged(self):
        for name in FROZEN+('TighteningTask','SpeedPiAntiWindup_Apply','SpeedBumpless_Apply',
                'MotorControl_SetSpeed','MotorControl_SetIq','Encoder_ElectricalAngleRad',
                'FocFeedbackSafety_Push','FocOcConfirm_Push','FocFp_PushRawSafety',
                'ProtectedLoop_PwmCommitPermit','LatestOriginal_Admit','IntentPort_Config'):
            old=function(self.before,name); new=function(self.after,name)
            if name=='FOC_EncoderSpeedUpdate':
                start=re.search(r'if \(mode == MOTOR_MODE_SPEED\) \{\s*SpeedBrakeTrackResult brake=',old).start()
                _,end=braced(old,start); old=old[:start]+old[end:]
                self.assertNotIn('SpeedBrakeTrack_Apply',new)
                self.assertIn('SpeedPiAntiWindup_Apply',new)
                self.assertEqual(new.count('foc_iq_ref_A = iq_cmd;'),1)
                self.assertIn('fabsf(encoder_speed_rpm) > 300.0f',new)
            self.assertEqual(re.sub(r'\s+','',old),re.sub(r'\s+','',new),name)
        for obj in ('foc_adc_timing_stm32.c.obj','stm32g4xx_it.c.obj'):
            data=[next((ROOT/f'foc2_app_a/build/{preset}').rglob(obj)).read_bytes()
                for preset in (BASE,PRESET)]
            self.assertEqual(*data,obj)

    def test_real_final_commit_keeps_aw_bounds_but_no_two_instant_speed_ceiling(self):
        code='''#include <assert.h>
#include <math.h>
#include "speed_pi_anti_windup.h"
#include "speed_brake_track.h"
#define MOTOR_MODE_SPEED 2
static float ClampFloat(float v,float lo,float hi) {return v<lo?lo:v>hi?hi:v;}
'''
        for name,source in (('on',self.before),('off',self.after)):
            outer=function(source,'FOC_EncoderSpeedUpdate')
            start=re.search(r'i_candidate\s*=\s*ClampFloat\(i_candidate',outer).start()
            finish=outer.index('foc_iq_ref_A = iq_cmd;',start)+len('foc_iq_ref_A = iq_cmd;')
            code+='''static void run_'''+name+'''(float prev,float candidate,float p,int mode,
    float ref,float speed,float instant,SpeedBrakeTrack *history,float *i,float *current) {
    float speed_integrator_A=prev,sb2_previous_A=prev,i_candidate=candidate,p_term=p;
    float speed_iq_limit_A=.5f,iq_unsat=0,iq_cmd=0,foc_iq_ref_A=0;
    float speed_ref_rpm=ref,encoder_speed_rpm=speed,rpm_inst=instant;
    unsigned speed_integrator_bleed_active=0,speed_overspeed_bleed_active=0;
    float speed_err=ref-speed; SpeedBrakeTrack speed_brake_track=*history;
    (void)rpm_inst; (void)speed_ref_rpm; (void)encoder_speed_rpm;
'''+outer[start:finish]+'''
    *i=speed_integrator_A; *current=foc_iq_ref_A; *history=speed_brake_track;
}
'''
        code+='''int main(void) {
  for(int sign=-1;sign<=1;sign+=2) {
    float s=(float)sign,oni,offi,onc,offc;
    SpeedBrakeTrack on={0},off={0};
    run_on(s*.2f,s*.2004f,s*.03f,2,s*20,s*10,s*30,&on,&oni,&onc);
    run_off(s*.2f,s*.2004f,s*.03f,2,s*20,s*10,s*30,&off,&offi,&offc);
    assert(oni==offi && onc==offc);
    run_on(oni,oni+s*.0004f,s*.03f,2,s*20,s*10,s*40,&on,&oni,&onc);
    run_off(offi,offi+s*.0004f,s*.03f,2,s*20,s*10,s*40,&off,&offi,&offc);
    assert(s*onc<0 && s*offc>0); /* only the explicit SB3 ceiling differs */
    run_off(s*.29f,s*.31f,s*.2f,2,s*240,s*170,s*170,&off,&offi,&offc);
    assert(fabsf(offi-s*.3f)<1e-6f && fabsf(offc-s*.5f)<1e-6f);
    on=(SpeedBrakeTrack){0}; off=on;
    run_on(s*.29f,s*.31f,s*.2f,1,s*240,s*170,s*170,&on,&oni,&onc);
    run_off(s*.29f,s*.31f,s*.2f,1,s*240,s*170,s*170,&off,&offi,&offc);
    assert(oni==offi && onc==offc); /* POSITION remains original */
  }
  return 0;
}'''
        awtest.SpeedAntiWindupTests.compile_run(self,code,'actual_no_sb3')

    def test_defaults_identity_macros_and_warnings(self):
        macros=[]; warnings=[]
        for preset in (BASE,PRESET):
            base=ROOT/f'foc2_app_a/build/{preset}'
            cmd=next(c['command'] for c in json.loads((base/'compile_commands.json').read_text())
                if c['file'].endswith('/Core/Src/main.c'))
            pp=subprocess.run(re.sub(r' -o \S+ -c ',' -E -dM ',cmd),cwd=base,
                capture_output=True,text=True,check=True).stdout
            macros.append(dict(re.findall(r'^#define (\w+) (.*)$',pp,re.M)))
            check=subprocess.run(re.sub(r' -o \S+ -c ',' -fsyntax-only ',cmd),cwd=base,
                capture_output=True,text=True,check=True)
            warnings.append(set(re.findall(r'warning: (.*)',check.stderr)))
        for name,value in macros[0].items():
            if name not in ('__TIME__','__DATE__','__TIMESTAMP__'):
                self.assertEqual(value,macros[1].get(name),name)
        self.assertEqual(set(macros[1])-set(macros[0]),{'FOC_SPEED_SB3_DISABLE_CANDIDATE'})
        self.assertFalse(warnings[1]-warnings[0])
        cm=(ROOT/'foc2_app_a/CMakeLists.txt').read_text()
        self.assertRegex(cm,r'option\(FOC_SPEED_SB3_DISABLE_CANDIDATE [^\n]+ OFF\)')
        self.assertNotIn('FOC_SPEED_SB3_DISABLE_CANDIDATE',(ROOT/'foc2_app_b/CMakeLists.txt').read_text())
        data=(ROOT/f'foc2_app_a/build/{PRESET}/foc2.bin').read_bytes()
        self.assertIn(b'SPEED_CTRL=AW0',data); self.assertNotIn(b'SPEED_CTRL=AW1',data)
        self.assertIn(b'TRIP_MA=4000',data); self.assertLessEqual(len(data),229376)

    def test_old_aw1_and_b_images_preserved(self):
        for path,sha in ((f'foc2_app_a/build/{BASE}/foc2.bin',
            'd1c7a791540c51c4aa9967cb5202a488514f6d47a1ff43321a50c80a9c90bc6a'),
            ('foc2_app_b/build/TighteningCommonModeCandidate/foc2.bin',
            '7ebdb56408baaa6c213c5dabe236250be673ed5a5c1345dfe64861d1e98dd366')):
            self.assertEqual(hashlib.sha256((ROOT/path).read_bytes()).hexdigest(),sha)


if __name__=='__main__': unittest.main()
