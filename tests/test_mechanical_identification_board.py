import json
from pathlib import Path
import re
import subprocess
import sys
import unittest
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
import mechanical_identification_board as board
import current_pi_compare as compiler
from test_torque_chain import function
from test_torque350_five_second import expanded


class BoardTests(unittest.TestCase):
    def test_exact_image_numeric_ka_and_gates_before_setup(self):
        board.image()
        self.assertEqual(board.KA,.000046875)
        self.assertEqual(board.POINTS,(100,-100,200,-200,240,-240))
        with patch.object(board,'setup') as setup:
            for args in (['--prepare-off'],['--execute-six','missing'],['--restore-b-drive-off','missing']):
                with self.assertRaises(SystemExit):board.main(args)
            setup.assert_not_called()

    def test_fixed_bemf_readback(self):
        board.bemf_status('OK ON=1 CONFIGURED=1 PSI_NWB=348660 DQ_CROSS=0')
        for line in ('OK ON=0 CONFIGURED=1 PSI_NWB=348660 DQ_CROSS=0',
                     'OK ON=1 CONFIGURED=1 PSI_NWB=697320 DQ_CROSS=0'):
            with self.assertRaises(RuntimeError):board.bemf_status(line)
        board.rest_status('OK FLT=0 BUSY=0 MODE=IDLE CTRL=0.1rpm DET=-0.1rpm')
        for line in ('OK FLT=0 BUSY=0 MODE=IDLE CTRL=3rpm DET=0rpm',
                     'OK FLT=0 BUSY=0 MODE=IDLE CTRL=nanrpm DET=0rpm',
                     'OK FLT=1 BUSY=0 MODE=IDLE CTRL=0rpm DET=0rpm'):
            with self.assertRaises(RuntimeError):board.rest_status(line)

    def test_same_control_math_irqs_and_single_existing_power_owner(self):
        normal=expanded('a','MechanicalIdentificationCandidate')
        motion=expanded('a','MechanicalIdentificationMotionCandidate')
        for name in ('FOC_CurrentLoopStep','ProtectedLoop_AdcIrq','ProtectedLoop_PwmEntry',
            'ProtectedLoop_SetDuty','ProtectedLoop_TimerHealthy','ProtectedLoop_GuardIrqBody',
            'PowerStage_Enable','PowerStage_Disable','Encoder_ElectricalAngleRad',
            'MotorControl_SetSpeed','MotorControl_SetIq'):
            self.assertEqual(function(normal,name),function(motion,name),name)
        admit=function(motion,'LatestOriginal_Admit')
        self.assertIn('ClSession_Queue',admit);self.assertIn('ClSession_Start',admit)
        self.assertEqual(len(re.findall(r'CCER\s*=\s*0x555U',admit)),1)
        self.assertIn('MotorControl_SetSpeed((float)friction_calibration.rpm)',admit)
        a=ROOT/'foc2_app_a/build/MechanicalIdentificationCandidate'
        b=ROOT/'foc2_app_a/build/MechanicalIdentificationMotionCandidate'
        for name in ('stm32g4xx_it.c.obj','foc_adc_timing_stm32.c.obj','as5047p_dma_stm32.c.obj',
                     'foc_zero_robust.c.obj','tightening_intent_fsm.c.obj'):
            self.assertEqual(next(a.rglob(name)).read_bytes(),next(b.rglob(name)).read_bytes(),name)

    def test_native_exact_six_commands_and_output_off_single_use_admission(self):
        binding=(ROOT/'firmware_common/friction_calibration_binding.inc').read_text()
        start=binding.index('static uint8_t FrictionCalibration_Command')
        command=binding[start:binding.index('__attribute__((optimize("Os")))',start)]
        code=r'''
#include <assert.h>
#include <stdio.h>
#include <string.h>
#define FOC_MECHANICAL_MOTION_DIAG 1
#include "friction_calibration.h"
#define CL_READY 1
#define MOTOR_MODE_IDLE 0
#define TIM_BDTR_MOE 0x8000u
#define TIM_BDTR_AOE 0x4000u
#define DRIVER_SD_Pin 64u
static FrictionCalibration friction_calibration;
static struct {unsigned used,state;} cl_session;
static struct {unsigned ODR;} gpio;
static struct {unsigned BDTR,CCER;} tim;
#define DRIVER_SD_GPIO_Port (&gpio)
#define TIM1 (&tim)
static unsigned speed_friction_enabled=1,busy,ready=1,tightening_start_request,tightening_stop_request,motor_control_mode;
static unsigned ProtectedLoop_Ready(void){return ready;}
static unsigned Tightening_IsBusy(void){return busy;}
#define taskENTER_CRITICAL() ((void)0)
#define taskEXIT_CRITICAL() ((void)0)
''' + command + r'''
int main(void){char out[384];int32_t rpm;
const char *good[]={"MOTOR TEST MECH RUN POS 100","MOTOR TEST MECH RUN NEG 100",
 "MOTOR TEST MECH RUN POS 200","MOTOR TEST MECH RUN NEG 200",
 "MOTOR TEST MECH RUN POS 240","MOTOR TEST MECH RUN NEG 240"};
int values[]={100,-100,200,-200,240,-240};
for(unsigned i=0;i<6;i++){assert(Fcal_Parse(good[i],&rpm) && rpm==values[i]);}
const char *bad[]={"START","MOTOR TEST FCAL RUN POS 240","MOTOR TEST MECH RUN POS 300",
 "MOTOR TEST MECH RUN POS 100x","MOTOR TEST MECH RUN NEG -100"};
for(unsigned i=0;i<5;i++)assert(!Fcal_Parse(bad[i],&rpm));
cl_session.state=CL_READY;
unsigned *blockers[]={&busy,&cl_session.used,&tightening_start_request,
 &tightening_stop_request,&motor_control_mode,&gpio.ODR,&tim.BDTR,&tim.CCER};
for(unsigned k=0;k<8;k++){
 *blockers[k]=k==5?DRIVER_SD_Pin:k==6?TIM_BDTR_MOE:1;
 assert(FrictionCalibration_Command(good[0],out,sizeof out));
 assert(strstr(out,"ERR MECH NOT_READY") && !friction_calibration.used);
 *blockers[k]=0;
}
speed_friction_enabled=0;FrictionCalibration_Command(good[0],out,sizeof out);
assert(strstr(out,"ERR MECH NOT_READY"));speed_friction_enabled=1;
FrictionCalibration_Command(good[1],out,sizeof out);
assert(strstr(out,"OK MECH QUEUED RPM=-100"));
assert(friction_calibration.used && friction_calibration.queued && !friction_calibration.active);
FrictionCalibration_Command(good[2],out,sizeof out);assert(strstr(out,"ERR MECH NOT_READY"));
assert(!tim.CCER && !tim.BDTR && !gpio.ODR);
return 0;}
'''
        exe=ROOT/'tmp/mechanical-command-host.exe'
        p=subprocess.run([str(compiler.GCC),'-std=c11','-Os','-Wall','-Wextra','-Werror',
            '-I',str(ROOT/'firmware_common'),'-x','c','-','-o',str(exe)],input=code,text=True,capture_output=True)
        self.assertEqual(p.returncode,0,p.stdout+p.stderr)
        p=subprocess.run([str(exe)],text=True,capture_output=True)
        self.assertEqual(p.returncode,0,p.stdout+p.stderr)

    def test_independent_protection_never_advances_to_next_point(self):
        parent=dict(operator_present_whole_batch=True,attempts=[],runs=[],receipt_path='batch')
        row=dict(receipt_path='run',final_cpu_halted=True)
        plan=dict(speeds_rpm=list(board.POINTS),ka_a_per_rpm_s=board.KA)
        with patch.object(Path,'read_text',return_value=json.dumps(plan)),\
             patch.object(board,'image',return_value=b'image'),\
             patch.object(board.base,'staged',return_value=(Path('source'),b'before')),\
             patch.object(board.prior,'new_run',return_value=row),patch.object(board.prior,'checkpoint'),\
             patch.object(board,'run_point',side_effect=RuntimeError('independent protection')) as run:
            with self.assertRaisesRegex(RuntimeError,'independent protection'):board.execute(Path('plan'),parent)
            self.assertEqual(run.call_count,1);self.assertEqual(parent['runs'],[])

    def test_six_points_finish_even_if_fit_quality_is_poor_no_parameters_written(self):
        parent=dict(operator_present_whole_batch=True,attempts=[],runs=[],receipt_path='batch')
        plan=dict(speeds_rpm=list(board.POINTS),ka_a_per_rpm_s=board.KA)
        def new(*args):return dict(receipt_path='run'+str(args[-1]))
        def run(row,*args):row.update(final_capture='capture',final_outputs_off=True,final_cpu_halted=True,
            mechanical_capture=dict(meta=dict(count=100,flags=0)))
        with patch.object(Path,'read_text',return_value=json.dumps(plan)),patch.object(Path,'read_bytes',return_value=b'capture'),\
             patch.object(board,'image',return_value=b'image'),\
             patch.object(board.base,'staged',return_value=(Path('source'),b'before')),\
             patch.object(board.prior,'new_run',side_effect=new),patch.object(board.prior,'checkpoint'),\
             patch.object(board,'run_point',side_effect=run) as execute,\
             patch.object(board.analysis,'decode',return_value=dict(rows=[],board_verified=True)),\
             patch.object(board.analysis,'report',return_value=dict(normalized_qualified=False,parameter_writes=False)):
            board.execute(Path('plan'),parent)
            self.assertEqual(execute.call_count,6);self.assertTrue(parent['pass_'])
            self.assertFalse(parent['identification']['normalized_qualified'])
            self.assertFalse(parent['identification']['parameter_writes'])


if __name__=='__main__':unittest.main()
