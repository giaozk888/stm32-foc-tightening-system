"""User-requested normal500rpm protection, both guard paths; files only."""
import hashlib
import json
import math
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tests'));sys.path.insert(0,str(ROOT/'tools'))
from test_dob_real_trace import expanded
from test_torque_chain import function,GCC
from test_rundown240_candidate import BASE_FLAGS,CANDIDATE_FLAGS
import dob_trend500_board as board

class Normal500Tests(unittest.TestCase):
    def test_native_actual_fast_guard_boundaries_both_directions(self):
        for opt in ('-Os','-O2'):
            exe=ROOT/'tmp'/('normal-trip500'+opt+'.exe')
            source='''#include <assert.h>
#include <math.h>
#include "protected_closed_loop.h"
#include "foc_guard_integer.h"
_Static_assert(CL_OVERSPEED_RPM==500U,"Shared IRQ guard500");
_Static_assert(CL_SPEED_RPM==240U,"Target240 unchanged");
_Static_assert(CL_MAX_US==12000000U,"Original session lease");
_Static_assert(FOC_RUNDOWN240_MAX_TRAVEL_DEG==20000U,"Original travel");
int main(void){
 float limit=CL_OVERSPEED_RPM;
 float values[]={0,300.18f,-300.18f,499.99f,-499.99f,500,-500,500.01f,-500.01f,INFINITY,-INFINITY,NAN};
 for(unsigned k=0;k<12;++k){
   volatile float v=values[k];
   assert((int)FocGuard_Within(&v,&limit)==(int)(isfinite(v)&&fabsf(v)<=500));
 }
 assert(FOC_RUNDOWN240_IQ_LIMIT_A==.50f);
 return 0;
}
'''
            p=subprocess.run([GCC,'-std=c11',opt,'-Wall','-Wextra','-Werror',*BASE_FLAGS,*CANDIDATE_FLAGS,
                '-DFOC_RUNDOWN240_TRAVEL20000=1','-DFOC_DOB_NORMAL_CONTROL=1','-DFOC_NORMAL_RUN_TRIP500=1',
                '-DFOC_GUARD_FAST_PATH=1','-DFOC_PAIR_FAST_PATH=1',
                '-DFOC_FAST_MATH=1','-DAS5047P_DMA_IRQ_PREEMPT_ADC=1',
                '-I',str(ROOT/'firmware_common'),'-x','c','-','-o',str(exe)],input=source,text=True,capture_output=True)
            self.assertEqual(p.returncode,0,p.stdout+p.stderr)
            self.assertEqual(subprocess.run([str(exe)]).returncode,0)

    def test_both_actual_built_profiles_have500_and_no_identification_mode(self):
        for preset in ('TighteningDob025Trip500','DobTrendShadowTrip500Candidate'):
            source=expanded(preset)
            self.assertIn('CL_OVERSPEED_RPM=500U',source)
            data=(ROOT/'foc2_app_a/build'/preset/'foc2.bin').read_bytes()
            self.assertTrue(b'RUNDOWN240: RAM=240rpm TRIP=500rpm SAVE=OFF' in data)
            speed=function(source,'FOC_EncoderSpeedUpdate')
            self.assertIn('if (fabsf(encoder_speed_rpm) > ((float)500U))',speed)
            self.assertIn('PowerStage_Disable();',speed)
            self.assertIn('.hard_speed_limit_rpm=CL_OVERSPEED_RPM',function(source,'IntentPort_Config'))
            self.assertIn('CL_OVERSPEED_RPM',function(source,'ProtectedLoop_HealthCaptured'))
            command=next(c['command'] for c in json.loads((ROOT/'foc2_app_a/build'/preset/'compile_commands.json').read_text()) if c['file'].endswith('/Core/Src/main.c'))
            for flag in ('FOC_PSI_IDENT_DIAG','FOC_PSI_IDENT_TRIP500','FOC_MECHANICAL_HIGH_SPEED_DIAG'):
                self.assertNotIn('-D'+flag+'=1 ',command)

    def test_only_speed_threshold_changes_original_control_and_safety_owners(self):
        old,new=(expanded(p) for p in ('DobTrendShadowCandidate','DobTrendShadowTrip500Candidate'))
        for name in ('FOC_CurrentLoopStep','ProtectedLoop_AdcIrq','ProtectedLoop_GuardIrqBody',
                     'ProtectedLoop_Ready','LatestOriginal_Admit','PowerStage_Enable','PowerStage_Disable',
                     'MotorControl_SetIq','MotorControl_SetSpeed','Encoder_ElectricalAngleRad',
                     'ProtectedLoop_TaskService','TighteningTask','OuterObservation_Flush','IntentPort_Config'):
            self.assertEqual(function(old,name),function(new,name),name)
        before=function(old,'FOC_EncoderSpeedUpdate');after=function(new,'FOC_EncoderSpeedUpdate')
        self.assertEqual(after.count('((float)500U)'),1)
        self.assertEqual(before,after.replace('((float)500U)','300.0f'))

    def test_normal_default500_selected_and_original_B_binary_unchanged(self):
        presets=json.loads((ROOT/'foc2_app_a/CMakePresets.json').read_text())['configurePresets']
        normal=next(x for x in presets if x['name']=='TighteningDob025')
        self.assertEqual(normal['cacheVariables']['FOC_NORMAL_RUN_TRIP500'],'ON')
        self.assertNotIn('FOC_NORMAL_RUN_TRIP500',(ROOT/'foc2_app_b/CMakeLists.txt').read_text())
        p=ROOT/'foc2_app_b/build/MechanicalReviewB/foc2.bin'
        self.assertEqual(hashlib.sha256(p.read_bytes()).hexdigest(),'7ebdb56408baaa6c213c5dabe236250be673ed5a5c1345dfe64861d1e98dd366')

    def test_retest_still_requires_physical_gates(self):
        for args in (['--stage-off'],['--execute-powered','missing'],['--restore-b-drive-off','missing']):
            with patch.object(board,'configure') as configure:
                with self.assertRaises(SystemExit):board.main(args)
                configure.assert_not_called()

    def test_actual500_readback_required_before_original_single_start(self):
        class B:
            def __init__(self,trip):self.trip=trip
            def command(self,c):return 'OK DOBLIMITS '+' '.join(k+'='+v for k,v in dict(board.LIMITS,GUARD_RPM=self.trip).items())
        r={}
        with patch.object(board,'OLD_MOTION') as motion:
            with self.assertRaises(RuntimeError):board.motion(B('300'),r)
            motion.assert_not_called()
            board.motion(B('500'),r);motion.assert_called_once()

if __name__=='__main__':unittest.main()
