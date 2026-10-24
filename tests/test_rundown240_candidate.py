"""240rpm A-only configuration; compiled real FSM/storage, no board access."""
import ast
import hashlib
import json
from pathlib import Path
import re
import subprocess
import unittest
from test_torque_chain import GCC,FROZEN,function
from test_torque350_five_second import expanded

ROOT=Path(__file__).resolve().parents[1]
COMMON=ROOT/'firmware_common'
BASE_FLAGS=['-DFOC_PROTECTED_CLOSED_LOOP=1','-DFOC_CURRENT_TREND4=1',
    '-DFOC_CURRENT_SPIKE_ONLY=1','-DAS5047P_SPI_DMA=1','-DFOC_ADC_WINDOW=1',
    '-DFOC_ADC_SENSE_TOPOLOGY=2','-DFOC_LOADED_FSM_TRIAL=1','-DFOC_PWM_PIPELINE_CLOSED_LOOP=1']
CANDIDATE_FLAGS=['-DFOC_RUNDOWN240_CANDIDATE=1','-DFOC_INTENT_FSM_CANDIDATE=1',
    '-DFOC_PWM_COMMON_MODE_ENABLE=1']

class Rundown240Tests(unittest.TestCase):
    def test_compiled_ram_recipe_storage_guard_and_240_fsm(self):
        out=ROOT/'tests/rundown240_build'; out.mkdir(exist_ok=True)
        gxx=str(Path(GCC).with_name('g++.exe'))
        main=(ROOT/'foc2_app_a/Core/Src/main.c').read_text()
        helper='static void '+function(main,'TightenParams_ApplyRundown240Candidate')
        template=(ROOT/'tests/rundown240_candidate_host.cpp').read_text()
        for candidate,travel in ((False,False),(True,False),(True,True)):
            for opt in ('-Os','-O2'):
                flags=BASE_FLAGS+(CANDIDATE_FLAGS if candidate else [])
                if travel: flags=flags+['-DFOC_RUNDOWN240_TRAVEL20000=1']
                variant=str(candidate)+str(travel)
                objects=[]
                for source,compiler,std in (('tightening_intent_fsm.c',GCC,'c11'),
                        ('tighten_params.cpp',gxx,'c++17'),('tighten_params_storage.cpp',gxx,'c++17')):
                    obj=out/(variant+opt+source+'.obj'); objects.append(str(obj))
                    p=subprocess.run([compiler,'-std='+std,opt,'-Wall','-Wextra','-Werror',
                        '-I',str(COMMON),*flags,'-c',str(COMMON/source),'-o',str(obj)],capture_output=True,text=True,timeout=30)
                    self.assertEqual(p.returncode,0,p.stdout+p.stderr)
                source=template.replace('/* REAL_STARTUP_FUNCTION */',helper if candidate else '')
                exe=out/(variant+opt+'.exe')
                p=subprocess.run([gxx,'-std=c++17',opt,'-Wall','-Wextra','-Werror','-I',str(COMMON),
                    *flags,'-x','c++','-','-x','none',*objects,'-o',str(exe)],
                    input=source,capture_output=True,text=True,timeout=30)
                self.assertEqual(p.returncode,0,p.stdout+p.stderr)
                p=subprocess.run([str(exe)],capture_output=True,text=True,timeout=5)
                self.assertEqual(p.returncode,0,p.stdout+p.stderr)

    def test_separate_a_only_default_off_preset(self):
        cm=(ROOT/'foc2_app_a/CMakeLists.txt').read_text()
        self.assertRegex(cm,r'option\(FOC_RUNDOWN240_CANDIDATE [^\n]+ OFF\)')
        presets=json.loads((ROOT/'foc2_app_a/CMakePresets.json').read_text())
        p=next(p for p in presets['configurePresets'] if p['name']=='Tightening240rpmCandidate')
        self.assertEqual(p['inherits'],'TighteningCommonModeCandidate')
        self.assertEqual(p['cacheVariables'],{'FOC_RUNDOWN240_CANDIDATE':'ON'})
        self.assertNotIn('Tightening240rpmCandidate',(ROOT/'foc2_app_b/CMakePresets.json').read_text())
        for slot,expected in [('a','814d6254a29dfe186309f35b00a8dc1752a597f6bc8b51f2254f19dff03fa886'),
                              ('b','7ebdb56408baaa6c213c5dabe236250be673ed5a5c1345dfe64861d1e98dd366')]:
            self.assertEqual(hashlib.sha256((ROOT/f'foc2_app_{slot}/build/TighteningCommonModeCandidate/foc2.bin').read_bytes()).hexdigest(),expected)

    def test_controller_current_safety_and_pwm_pipeline_frozen(self):
        normal=expanded('a','TighteningCommonModeCandidate')
        candidate=expanded('a','Tightening240rpmCandidate')
        for name in FROZEN+('ProtectedLoop_PwmCommitPermit','LatestOriginal_Admit',
                'FocFeedbackSafety_Push','FocOcConfirm_Push','MotorControl_SetSpeed','MotorControl_SetIq',
                'Encoder_ElectricalAngleRad','IntentPort_Config'):
            before=function(normal,name); after=function(candidate,name)
            if name=='FOC_EncoderSpeedUpdate':
                # Only the SPEED-mode command ceiling may differ. Keep the
                # generic POSITION ceiling, gains, math and guards untouched.
                self.assertEqual(after.count('speed_iq_limit_A = 0.50f;'),1)
                after=after.replace('speed_iq_limit_A = 0.50f;','speed_iq_limit_A = 0.40f;')
            elif name=='IntentPort_Config':
                self.assertEqual(after.count('.speed_iq_limit_a=0.50f'),1)
                after=after.replace('.speed_iq_limit_a=0.50f','.speed_iq_limit_a=0.40f')
            self.assertEqual(before,after,name)
        self.assertIn('CL_SPEED_RPM=240U',candidate)
        self.assertIn('CL_OVERSPEED_RPM=300U',candidate)
        self.assertIn('RUNDOWN240: RAM=240rpm TRIP=300rpm SAVE=OFF',candidate)
        self.assertLess(candidate.index('TightenParams_ApplyRundown240Candidate();'),
                        candidate.index('xTaskCreate(MotorControlTask'))

    def test_real_speed_ceiling_and_port_both_allow_500ma_not_fixed_iq(self):
        candidate=expanded('a','Tightening240rpmCandidate')
        outer=function(candidate,'FOC_EncoderSpeedUpdate')
        match=re.search(r'speed_iq_limit_A\s*=\s*0\.50f;',outer)
        self.assertIsNotNone(match)
        # Compile the exact limit selection and the existing final saturation.
        clamp=re.search(r'iq_cmd\s*=\s*ClampFloat\(iq_unsat,\s*-speed_iq_limit_A,\s*speed_iq_limit_A\);',outer)
        self.assertIsNotNone(clamp)
        source='#include <assert.h>\nstatic float '+function(candidate,'ClampFloat')+'''
int main(void) {
    float speed_iq_limit_A=0.40f,iq_unsat,iq_cmd;
'''+match.group(0)+'''
    iq_unsat=.60f;
'''+clamp.group(0)+''' assert(iq_cmd==.50f);
    iq_unsat=-.60f;
'''+clamp.group(0)+''' assert(iq_cmd==-.50f);
    iq_unsat=.123f;
'''+clamp.group(0)+''' assert(iq_cmd==iq_unsat); return 0;
}
'''
        out=ROOT/'tests/rundown240_build'; out.mkdir(exist_ok=True)
        for opt in ('-Os','-O2'):
            exe=out/('speed500'+opt+'.exe')
            p=subprocess.run([GCC,'-std=c11',opt,'-Wall','-Wextra','-Werror','-x','c','-',
                '-o',str(exe)],input=source,capture_output=True,text=True,timeout=30)
            self.assertEqual(p.returncode,0,p.stdout+p.stderr)
            p=subprocess.run([str(exe)],capture_output=True,text=True,timeout=5)
            self.assertEqual(p.returncode,0,p.stdout+p.stderr)
        self.assertIn('.speed_iq_limit_a=0.50f',function(candidate,'IntentPort_Config'))
        self.assertIn('IntentPort_Stop,((void*)0),0.50f,0.20f,',
                      re.sub(r'\s+','',function(candidate,'TighteningTask')))
        self.assertIn('iq_unsat = p_term + i_candidate;',outer)

    def test_profile_is_complete_and_old_runner_cannot_accept_new_image(self):
        text=expanded('a','Tightening240rpmCandidate')
        profiles=re.findall(r'snprintf\(out,size,((?:\s*"[^"\n]*"\s*)+)\);',text)
        profile=next(p for p in profiles if 'PROTECTED_PIPELINE_CLOSED_LOOP' in p)
        profile=''.join(ast.literal_eval(s) for s in re.findall(r'"[^"\n]*"',profile))
        self.assertIn('RPM=240 ',profile)
        self.assertTrue(profile.endswith('QUALIFIED=0'))
        self.assertLess(len(profile),192)
        old=(ROOT/'tools/common_mode_fsm_board.py').read_text()
        self.assertIn("b'RPM=20 LEASE_US=12000000'",old)
        self.assertNotIn('Tightening240rpmCandidate',old)

    def test_cannot_enable_speed_option_without_protected_profile(self):
        p=subprocess.run([GCC,'-x','c','-','-fsyntax-only','-I',str(COMMON),
            '-DFOC_RUNDOWN240_CANDIDATE=1'],input='#include "foc_rundown240_candidate.h"\n',
            capture_output=True,text=True,timeout=10)
        self.assertNotEqual(p.returncode,0)
        self.assertIn('exclusive protected common-mode intent FSM',p.stderr)

if __name__=='__main__': unittest.main()
