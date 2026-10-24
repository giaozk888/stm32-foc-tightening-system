import hashlib
import json
import re
from pathlib import Path
import subprocess
import unittest
from test_torque_chain import GCC,function
from test_torque350_five_second import expanded
from test_dob_normal_control import FLAGS as BASE_FLAGS
ROOT=Path(__file__).resolve().parents[1]
GXX=str(Path(GCC).with_name('g++.exe'))
PRESET='TighteningDob025Contact20Observe10Candidate'
FLAGS=BASE_FLAGS+['-DFOC_DOB_CONTACT20_OBSERVE10=1']

def expanded_unit(suffix):
    build=ROOT/'foc2_app_a/build'/PRESET
    cmd=next(c['command'] for c in json.loads((build/'compile_commands.json').read_text()) if c['file'].endswith(suffix))
    p=subprocess.run(re.sub(r' -o \S+ -c ',' -E -P ',cmd),cwd=build,text=True,capture_output=True)
    if p.returncode:raise AssertionError(p.stderr)
    return p.stdout

class Contact20Observe10Tests(unittest.TestCase):
    def test_native_real_fsm_observer_feedback_boundaries_quality_and_no_parameter_write(self):
        for opt in ('-Os','-O2'):
            objects=[]
            for source in ('tests/dob_contact20_observe10_host.c','firmware_common/tightening_intent_fsm.c',
                           'firmware_common/mechanical_dob_monitor.c'):
                obj=ROOT/'tmp'/(Path(source).stem+'-c20-o10'+opt+'.o');objects.append(str(obj))
                p=subprocess.run([GCC,'-std=c11',opt,'-Wall','-Wextra','-Werror',*FLAGS,
                    '-I',str(ROOT/'firmware_common'),'-c',str(ROOT/source),'-o',str(obj)],text=True,capture_output=True)
                self.assertEqual(p.returncode,0,p.stdout+p.stderr)
            obj=ROOT/'tmp'/('c20-o10-params'+opt+'.o');objects.append(str(obj))
            p=subprocess.run([GXX,'-std=c++17',opt,'-Wall','-Wextra','-Werror','-I',str(ROOT/'firmware_common'),
                '-c',str(ROOT/'firmware_common/tighten_params.cpp'),'-o',str(obj)],text=True,capture_output=True)
            self.assertEqual(p.returncode,0,p.stdout+p.stderr)
            exe=ROOT/'tmp'/('c20-o10'+opt+'.exe')
            p=subprocess.run([GXX,*objects,'-o',str(exe)],text=True,capture_output=True)
            self.assertEqual(p.returncode,0,p.stdout+p.stderr)
            p=subprocess.run([str(exe)],text=True,capture_output=True)
            self.assertEqual(p.returncode,0,p.stdout+p.stderr);self.assertIn('PASS: CONTACT20',p.stdout)

    def test_actual_profile_overlay_after_loaded_recipe_preserves_other_fields(self):
        source=expanded('a',PRESET)
        overlay=function(source,'TightenParams_ApplyRundown240Candidate')
        self.assertIn('recipe_state.params.contact_rpm=20U;',overlay)
        self.assertEqual(overlay.count('recipe_state.params.'),3) # rundown/travel/contact only.
        startup=function(source,'StartupTask')
        self.assertLess(startup.index('TightenParams_LoadFromFlash'),startup.index('TightenParams_ApplyRundown240Candidate'))
        self.assertIn('SAVE=OFF; manual START',source)
        save=function(expanded_unit('/tighten_params_storage.cpp'),'TightenParams_StorageSave')
        self.assertNotIn('port->save',save)
        self.assertIn('return 0U;',save)
        # Exercise the compiled overlay with an arbitrary existing contact value.
        code='''#include <assert.h>\n#include <stdint.h>\n#include "tighten_params.h"\nstatic struct {TightenParams_t params;unsigned dirty;} recipe_state;\nstatic void '''+overlay+'''
int main(void){
 recipe_state.params=(TightenParams_t)TIGHTEN_PARAMS_DEFAULT_INITIALIZER;
 recipe_state.params.contact_rpm=7;
 TightenParams_t expected=recipe_state.params;
 expected.rundown_rpm=240;expected.max_travel_deg=20000;expected.contact_rpm=20;
 TightenParams_ApplyRundown240Candidate();assert(recipe_state.dirty);
 const uint32_t *a=(const uint32_t *)&recipe_state.params,*b=(const uint32_t *)&expected;
 for(unsigned i=0;i<18;i++)assert(a[i]==b[i]);return 0;}
'''
        exe=ROOT/'tmp/c20-o10-overlay.exe'
        p=subprocess.run([GCC,'-std=c11','-Os','-I',str(ROOT/'firmware_common'),'-x','c','-',
            '-o',str(exe)],input=code,text=True,capture_output=True)
        self.assertEqual(p.returncode,0,p.stdout+p.stderr)
        self.assertEqual(subprocess.run([str(exe)]).returncode,0)

    def test_only_recipe_model_min_and_fresh_source_qualification_change(self):
        old,new=(expanded('a',p) for p in ('TighteningDob025',PRESET))
        for name in ('FOC_CurrentLoopStep','ProtectedLoop_AdcIrq','ProtectedLoop_GuardIrqBody',
            'ProtectedLoop_Ready','LatestOriginal_Admit','PowerStage_Enable','PowerStage_Disable',
            'MotorControl_SetIq','MotorControl_SetSpeed','Encoder_ElectricalAngleRad','ProtectedLoop_TaskService',
            'TighteningTask','OuterObservation_Flush'):
            self.assertEqual(function(old,name),function(new,name),name)
        self.assertIn('DobObserve10_FeedbackSpeedQualified(mechanical_dob_monitor.current.omega_rad_s)',
                      function(new,'FOC_EncoderSpeedUpdate'))
        self.assertIn('float raw=0.25f*estimate',new)
        self.assertTrue('.min_speed_rad_s=1.0471975511965977f' in expanded_unit('/mechanical_dob_monitor.c'))
        self.assertTrue('OBS_MIN_MRPM=10000 FB_MIN_MRPM=20000' in new)
        self.assertIn('CL_OVERSPEED_RPM=300U',new)
        self.assertIn('CL_MAX_US=12000000U',new)

    def test_old_normal_and_b_frozen_and_opt_in(self):
        b=ROOT/'foc2_app_a/build/TighteningDob025/foc2.bin'
        self.assertEqual(hashlib.sha256(b.read_bytes()).hexdigest(),
            '0a2fe20161d8fb77a494fe7cd1dcec23126f52e3f8534fbcd7ae6ac5d6afc3a5')
        self.assertNotIn('FOC_DOB_CONTACT20_OBSERVE10',(ROOT/'foc2_app_b/CMakeLists.txt').read_text())
        presets=json.loads((ROOT/'foc2_app_a/CMakePresets.json').read_text())['configurePresets']
        self.assertEqual([p['name'] for p in presets if p.get('cacheVariables',{}).get('FOC_DOB_CONTACT20_OBSERVE10')=='ON'],[PRESET])
        self.assertEqual(hashlib.sha256((ROOT/'foc2_app_b/build/MechanicalReviewB/foc2.bin').read_bytes()).hexdigest(),
            '7ebdb56408baaa6c213c5dabe236250be673ed5a5c1345dfe64861d1e98dd366')

if __name__=='__main__':unittest.main()
