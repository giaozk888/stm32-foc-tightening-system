import json
from pathlib import Path
import subprocess
import unittest
from test_torque_chain import GCC,function
from test_torque350_five_second import expanded
from test_dob_id_pre_lpf import FLAGS as BASE_FLAGS
ROOT=Path(__file__).resolve().parents[1]

class FeedbackTests(unittest.TestCase):
    def test_guarded_manual_switch_truthful_feedback_and_protocol_capacity(self):
        code=r'''
#include <assert.h>
#include <stdio.h>
#include <string.h>
#include "mechanical_dob_monitor.h"
#include "dob_id_trace.h"
#include "dob_feedback_candidate.h"
static MechanicalDobMonitor mechanical_dob_monitor;
static DobFeedbackCandidate dob_feedback;
static unsigned cl_armed,adc_fault,foc_fault,busy,tightening_start_request,tightening_stop_request,motor_control_mode;
static struct {unsigned state;} cl_session;
static struct {unsigned ODR;} driver;
static struct {unsigned BDTR,CCER;} timer;
#define DRIVER_SD_GPIO_Port (&driver)
#define DRIVER_SD_Pin 64U
#define TIM1 (&timer)
#define TIM_BDTR_MOE 32768U
#define TIM_BDTR_AOE 16384U
#define CL_RUNNING 2U
#define MOTOR_MODE_IDLE 0U
#define taskENTER_CRITICAL() ((void)0)
#define taskEXIT_CRITICAL() ((void)0)
static unsigned Tightening_IsBusy(void){return busy;}
static uint32_t AS5047P_DmaNowUs(void){return 1000;}
'''+(ROOT/'firmware_common/mechanical_dob_binding.inc').read_text()+r'''
int main(void){char out[200];
assert(MechanicalDob_Command("MOTOR TEST MECH DOB FB CFG",out,192)&&strstr(out,"ON=0"));
assert(MechanicalDob_Command("MOTOR TEST MECH DOB FB ON",out,192)&&dob_feedback.enabled);
assert(MechanicalDob_Command("MOTOR TEST MECH DOB",out,192)&&strstr(out,"FEEDBACK=1"));
for(unsigned i=0;i<7;i++){
 busy=tightening_start_request=tightening_stop_request=motor_control_mode=driver.ODR=timer.BDTR=timer.CCER=0;
 switch(i){case 0:busy=1;break;case 1:tightening_start_request=1;break;case 2:tightening_stop_request=1;break;
 case 3:motor_control_mode=1;break;case 4:driver.ODR=DRIVER_SD_Pin;break;case 5:timer.BDTR=TIM_BDTR_MOE;break;default:timer.CCER=1;}
 assert(MechanicalDob_Command("MOTOR TEST MECH DOB FB OFF",out,192));
 assert(strstr(out,"ERR DOBFB BUSY_OR_OUTPUT_ENABLED")&&dob_feedback.enabled);
}
busy=tightening_start_request=tightening_stop_request=motor_control_mode=driver.ODR=timer.BDTR=timer.CCER=0;
assert(MechanicalDob_Command("MOTOR TEST MECH DOB FB OFF",out,192)&&!dob_feedback.enabled);
assert(MechanicalDob_Command("MOTOR TEST MECH DOB",out,192)&&strstr(out,"FEEDBACK=0"));
dob_feedback=(DobFeedbackCandidate){.enabled=1,.sample_us=UINT32_MAX,.age_us=UINT32_MAX,.state=5,
 .iq_comp_a=-3000,.disturbance_a=-3000,.iq_pi_a=-3000,.iq_raw_a=-3000,.iq_ref_a=-3000,.integral_a=-3000,
 .saturation=1,.updates=UINT32_MAX,.valid_updates=UINT32_MAX,.holds=UINT32_MAX,.fades=UINT32_MAX,
 .clears=UINT32_MAX,.clamps=UINT32_MAX,.peak_a=-3000};
const char *q[]={"STATUS","SUM","STATS","CFG"};
for(unsigned i=0;i<4;i++){char command[80];snprintf(command,sizeof command,"MOTOR TEST MECH DOB FB %s",q[i]);
 memset(out,'X',sizeof out);assert(MechanicalDob_Command(command,out,192));
 assert(strlen(out)<191);for(unsigned n=192;n<200;n++)assert(out[n]=='X');}
return 0;}
'''
        exe=ROOT/'tmp/dob-feedback-protocol.exe'
        p=subprocess.run([GCC,'-std=c11','-Os','-Wall','-Wextra','-Werror',*BASE_FLAGS,
            '-DFOC_DOB_FEEDBACK_CANDIDATE=1','-DDOB_ADMIT_JUMP_A=.200f',
            '-I',str(ROOT/'firmware_common'),str(ROOT/'firmware_common/mechanical_dob_monitor.c'),
            str(ROOT/'firmware_common/dob_id_trace.c'),'-x','c','-','-o',str(exe)],
            input=code,text=True,capture_output=True)
        self.assertEqual(p.returncode,0,p.stdout+p.stderr)
        p=subprocess.run([str(exe)],capture_output=True)
        self.assertEqual(p.returncode,0,p.stdout+p.stderr)

    def test_actual_native_hold_fade_slew_total_limit_aw_and_off_equivalence(self):
        for opt in ('-Os','-O2'):
            exe=ROOT/'tmp'/('dob-feedback'+opt+'.exe')
            p=subprocess.run([GCC,'-std=c11',opt,'-Wall','-Wextra','-Werror',
                '-I',str(ROOT/'firmware_common'),str(ROOT/'tests/dob_feedback_host.c'),
                str(ROOT/'firmware_common/speed_friction_compensation.c'),
                str(ROOT/'firmware_common/speed_accel_feedforward.c'),'-o',str(exe)],text=True,capture_output=True)
            self.assertEqual(p.returncode,0,p.stdout+p.stderr)
            p=subprocess.run([str(exe)],text=True,capture_output=True)
            self.assertEqual(p.returncode,0,p.stdout+p.stderr)
            self.assertIn('PASS: signed load compensation',p.stdout)

    def test_compiled_safety_foc_angle_pipeline_unchanged_only_speed_sum_and_lifecycle(self):
        old,new=(expanded('a',p) for p in ('MechanicalDobPreLpf200Candidate','MechanicalDobFeedbackCandidate'))
        for name in ('FOC_CurrentLoopStep','ProtectedLoop_AdcIrq','ProtectedLoop_GuardIrqBody',
            'ProtectedLoop_Ready','LatestOriginal_Admit','PowerStage_Enable','PowerStage_Disable',
            'MotorControl_SetIq','MotorControl_SetSpeed','Encoder_ElectricalAngleRad'):
            self.assertEqual(function(old,name),function(new,name),name)
        speed=function(new,'FOC_EncoderSpeedUpdate')
        self.assertIn('SpeedFrictionDob_Apply',speed)
        self.assertLess(speed.index('SpeedFrictionDob_Apply'),speed.index('speed_integrator_A=aff.integral_a'))
        self.assertIn('foc_iq_ref_A = iq_cmd;',speed)
        self.assertNotIn('FOC_DOB_FEEDBACK_CANDIDATE',(ROOT/'foc2_app_b/CMakeLists.txt').read_text())
        presets=json.loads((ROOT/'foc2_app_a/CMakePresets.json').read_text())['configurePresets']
        self.assertEqual([p['name'] for p in presets if p.get('cacheVariables',{}).get('FOC_DOB_FEEDBACK_CANDIDATE')=='ON'],
                         ['MechanicalDobFeedbackCandidate'])

if __name__=='__main__':unittest.main()
