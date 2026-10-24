"""A-only speed AW candidate: compiled boundaries and real call-site tests."""
import hashlib
import json
from pathlib import Path
import re
import subprocess
import unittest
from test_torque_chain import GCC,FROZEN,function
from test_torque350_five_second import expanded

ROOT=Path(__file__).resolve().parents[1]
PRESET='Tightening240rpmSpeedAntiWindupCandidate'
BASE='Tightening240rpmAdc100Return40Candidate'


def braced(src,start):
    brace=src.index('{',start); depth=1; end=brace+1
    while depth:
        depth+=(src[end]=='{')-(src[end]=='}'); end+=1
    return brace,end


class SpeedAntiWindupTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.out=ROOT/'tests/speed_pi_anti_windup_build'; cls.out.mkdir(exist_ok=True)
        cls.before=expanded('a',BASE); cls.after=expanded('a',PRESET)

    def compile_run(self,source,stem):
        for opt in ('-Os','-O2'):
            exe=self.out/(stem+opt+'.exe')
            result=subprocess.run([GCC,'-std=c11',opt,'-Wall','-Wextra','-Werror','-pedantic','-UNDEBUG',
                '-I',str(ROOT/'firmware_common'),'-x','c','-','-o',str(exe)],
                input=source,capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            result=subprocess.run([str(exe)],capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)

    def test_real_helpers_bounds_unwind_braking_recovery_at_os_o2(self):
        self.compile_run((ROOT/'tests/speed_pi_anti_windup_host.c').read_text(),'helper')

    def test_real_preprocessed_pi_commit_and_final_sb3_at_os_o2(self):
        code='''#include <assert.h>
#include <math.h>
#include "speed_pi_anti_windup.h"
#include "speed_brake_track.h"
#define MOTOR_MODE_SPEED 2
static float ClampFloat(float v,float lo,float hi) {return v<lo?lo:v>hi?hi:v;}
'''
        for name,source in (('old',self.before),('candidate',self.after)):
            outer=function(source,'FOC_EncoderSpeedUpdate')
            start=re.search(r'i_candidate\s*=\s*ClampFloat\(i_candidate',outer).start()
            finish=outer.index('foc_iq_ref_A = iq_cmd;',start)+len('foc_iq_ref_A = iq_cmd;')
            fragment=outer[start:finish]
            code+='''static void run_'''+name+'''(float prev,float candidate,float p,int mode,int release,
    float ref,float speed,float instant,SpeedBrakeTrack *history,float *i,float *current) {
    float speed_integrator_A=prev,sb2_previous_A=prev,i_candidate=candidate,p_term=p;
    float speed_iq_limit_A=.5f,iq_unsat=0,iq_cmd=0,foc_iq_ref_A=0;
    float speed_ref_rpm=ref,encoder_speed_rpm=speed,rpm_inst=instant;
    unsigned speed_integrator_bleed_active=0,speed_overspeed_bleed_active=(unsigned)release;
    float speed_err=ref-speed; SpeedBrakeTrack speed_brake_track=*history;
    (void)sb2_previous_A;
'''+fragment+'''
    *i=speed_integrator_A; *current=foc_iq_ref_A; *history=speed_brake_track;
}
'''
        code+='''int main(void) {
  float oi,ni,oc,nc; SpeedBrakeTrack os={0},ns={0};
  /* Partial boundary: old code sends candidate but stores older I. */
  run_old(.29f,.31f,.2f,2,0,240,173.3333f,173.3333f,&os,&oi,&oc);
  run_candidate(.29f,.31f,.2f,2,0,240,173.3333f,173.3333f,&ns,&ni,&nc);
  assert(fabsf(oi-.29f)<1e-6f && fabsf(ni-.30f)<1e-6f && fabsf(nc-.5f)<1e-6f);
  /* POSITION retains exact historical branch, both saturation signs. */
  for(int sign=-1;sign<=1;sign+=2) {
    os=(SpeedBrakeTrack){0}; ns=os;
    run_old(sign*.29f,sign*.31f,sign*.2f,1,0,sign*240,sign*173,sign*173,&os,&oi,&oc);
    run_candidate(sign*.29f,sign*.31f,sign*.2f,1,0,sign*240,sign*173,sign*173,&ns,&ni,&nc);
    assert(oi==ni && oc==nc);
  }
  /* Unsaturated + no brake: old and new match bit for bit. */
  os=(SpeedBrakeTrack){0}; ns=os;
  run_old(.1f,.11f,.03f,2,0,20,10,10,&os,&oi,&oc);
  run_candidate(.1f,.11f,.03f,2,0,20,10,10,&ns,&ni,&nc);
  assert(oi==ni && oc==nc);
  /* Existing SB3 two-sample braking still wins after AW and tracks I. */
  ns=(SpeedBrakeTrack){0};
  run_candidate(.2f,.2004f,.03f,2,0,20,10,30,&ns,&ni,&nc);
  run_candidate(ni,ni+.0004f,.03f,2,0,20,10,40,&ns,&ni,&nc);
  assert(fabsf(nc+.03f)<1e-6f && fabsf(ni+.06f)<1e-6f);
  return 0;
}'''
        # Both wrappers use real application code, not a handwritten PI approximation.
        self.compile_run(code,'actual_owner')

    def test_only_speed_pi_admission_changes_no_fsm_current_protection_or_ramp(self):
        names=FROZEN+('TighteningTask','SpeedBumpless_Apply','SpeedBrakeTrack_Apply',
            'MotorControl_SetSpeed','MotorControl_SetIq','Encoder_ElectricalAngleRad',
            'FocFeedbackSafety_Push','FocOcConfirm_Push','FocFp_PushRawSafety',
            'ProtectedLoop_PwmCommitPermit','LatestOriginal_Admit','IntentPort_Config')
        for name in names:
            old=function(self.before,name); new=function(self.after,name)
            if name=='FOC_EncoderSpeedUpdate':
                start=re.search(r'if \(mode == MOTOR_MODE_SPEED\) \{\s*SpeedPiAntiWindupResult aw=',new).start()
                _,end=braced(new,start)
                self.assertRegex(new[end:],r'^\s*else\s*\{')
                legacy_start,legacy_end=braced(new,end)
                # Removing the new SPEED-only selection restores the entire old outer loop.
                new=new[:start]+new[legacy_start+1:legacy_end-1]+new[legacy_end:]
            self.assertEqual(re.sub(r'\s+','',old),re.sub(r'\s+','',new),name)
        for source in (self.before,self.after):
            outer=function(source,'FOC_EncoderSpeedUpdate')
            self.assertEqual(outer.count('foc_iq_ref_A = iq_cmd;'),1)
        outer=function(self.after,'FOC_EncoderSpeedUpdate')
        self.assertLess(outer.index('SpeedPiAntiWindup_Apply'),outer.index('SpeedBrakeTrack_Apply'))
        self.assertLess(outer.index('SpeedBrakeTrack_Apply'),outer.index('foc_iq_ref_A = iq_cmd;'))
        for basename in ('foc_adc_timing_stm32.c.obj','stm32g4xx_it.c.obj'):
            objects=[next((ROOT/f'foc2_app_a/build/{preset}').rglob(basename)).read_bytes()
                for preset in (BASE,PRESET)]
            self.assertEqual(*objects,basename)

    def test_gains_limits_frequencies_and_warnings_unchanged(self):
        macros=[]; warnings=[]
        for preset in (BASE,PRESET):
            base=ROOT/f'foc2_app_a/build/{preset}'
            command=next(c['command'] for c in json.loads((base/'compile_commands.json').read_text())
                if c['file'].endswith('/Core/Src/main.c'))
            output=subprocess.run(re.sub(r' -o \S+ -c ',' -E -dM ',command),cwd=base,
                capture_output=True,text=True,check=True).stdout
            macros.append(dict(re.findall(r'^#define (\w+) (.*)$',output,re.M)))
            check=subprocess.run(re.sub(r' -o \S+ -c ',' -fsyntax-only ',command),cwd=base,
                capture_output=True,text=True,check=True)
            warnings.append(set(re.findall(r'warning: (.*)',check.stderr)))
        for name,value in macros[0].items():
            if name in ('__TIME__','__DATE__','__TIMESTAMP__'): continue
            self.assertEqual(value,macros[1].get(name),name)
        self.assertEqual(set(macros[1])-set(macros[0]),
            {'FOC_SPEED_PI_ANTI_WINDUP','SPEED_PI_ANTI_WINDUP_H'})
        self.assertFalse(warnings[1]-warnings[0],warnings[1]-warnings[0])
        data=(ROOT/f'foc2_app_a/build/{PRESET}/foc2.bin').read_bytes()
        self.assertIn(b'SPEED_CTRL=AW1',data)
        self.assertLessEqual(len(data),229376)

    def test_a_only_default_off_baseline_and_b_hashes_preserved(self):
        a=(ROOT/'foc2_app_a/CMakeLists.txt').read_text()
        self.assertRegex(a,r'option\(FOC_SPEED_PI_ANTI_WINDUP [^\n]+ OFF\)')
        self.assertNotIn('FOC_SPEED_PI_ANTI_WINDUP',(ROOT/'foc2_app_b/CMakeLists.txt').read_text())
        presets=json.loads((ROOT/'foc2_app_a/CMakePresets.json').read_text())
        preset=next(p for p in presets['configurePresets'] if p['name']==PRESET)
        self.assertEqual(preset['inherits'],BASE)
        self.assertEqual(preset['cacheVariables'],{'FOC_SPEED_PI_ANTI_WINDUP':'ON'})
        for path,sha in ((f'foc2_app_a/build/{BASE}/foc2.bin',
            'a1e158f50c3809c96d9df39f3c52353a2ed4b50bb02e911a4824437e25da5cdd'),
            ('foc2_app_b/build/TighteningCommonModeCandidate/foc2.bin',
             '7ebdb56408baaa6c213c5dabe236250be673ed5a5c1345dfe64861d1e98dd366')):
            self.assertEqual(hashlib.sha256((ROOT/path).read_bytes()).hexdigest(),sha)

    def test_incomplete_profile_is_compile_error(self):
        for flag in ('FOC_SPEED_BRAKE_TRACK','FOC_ADC_COUNTS_100_40_CANDIDATE'):
            result=subprocess.run([GCC,'-std=c11','-fsyntax-only','-x','c',
                '-DFOC_SPEED_PI_ANTI_WINDUP=1','-D'+flag+'=1','-I',str(ROOT/'firmware_common'),'-'],
                input='#include "speed_pi_anti_windup.h"\n',capture_output=True,text=True)
            self.assertNotEqual(result.returncode,0)
            self.assertIn('Speed anti-windup requires',result.stderr)


if __name__=='__main__': unittest.main()
