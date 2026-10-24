import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import unittest
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
import mechanical_high_speed_board as high
import mechanical_identification_board as low
import current_pi_compare as compiler
from test_torque_chain import function
from test_torque350_five_second import expanded


class HighSpeedTests(unittest.TestCase):
    def test_exact_image_order_and_no_parameter_change(self):
        high.image()
        self.assertEqual(high.POINTS,(500,)*3+(600,)*3+(700,)*3+(800,)*3)
        self.assertEqual(low.KA,.000046875)
        self.assertEqual(low.PSI,.00034866)
        self.assertEqual(hashlib.sha256((ROOT/'foc2_app_b/build/FrictionBUnchanged/foc2.bin').read_bytes()).hexdigest(),
            '7ebdb56408baaa6c213c5dabe236250be673ed5a5c1345dfe64861d1e98dd366')

    def test_gate_before_hardware_setup(self):
        with patch.multiple(low,setup=low.setup,POINTS=low.POINTS,TRIP_RPM=low.TRIP_RPM,
            TRAVEL_DEG=low.TRAVEL_DEG,CLOSURE_SECONDS=low.CLOSURE_SECONDS,LIMITS_QUERY=low.LIMITS_QUERY),\
             patch.object(high,'ORIGINAL_SETUP') as setup:
            for args in (['--prepare-off'],['--execute-twelve','missing'],['--restore-b-drive-off','missing']):
                with self.assertRaises(SystemExit):high.main(args)
            setup.assert_not_called()

    def test_native_whitelist_bounds_and_full_scurve_stop(self):
        code=r'''
#include <assert.h>
#include <stdio.h>
#define FOC_RUNDOWN240_CANDIDATE 1
#define FOC_INTENT_FSM_CANDIDATE 1
#define FOC_PWM_COMMON_MODE_ENABLE 1
#define FOC_LOADED_FSM_TRIAL 1
#define FOC_PWM_PIPELINE_CLOSED_LOOP 1
#define FOC_RUNDOWN240_TRAVEL20000 1
#define FOC_MECHANICAL_HIGH_SPEED_DIAG 1
#define FOC_MECHANICAL_MOTION_DIAG 1
#define FOC_MECHANICAL_IDENT_DIAG 1
#define FOC_FRICTION_CALIBRATION_DIAG 1
#include "foc_rundown240_candidate.h"
#include "friction_calibration.h"
#include "speed_scurve.h"
int main(void){
assert(FOC_RUNDOWN240_TRIP_RPM==1000);
assert(FOC_RUNDOWN240_MAX_TRAVEL_DEG==30000);
assert(FOC_RUNDOWN240_IQ_LIMIT_A==.5f);
assert(FCAL_DRIVE_MS==5000 && FCAL_STOP_MS==10500 && FCAL_STOP_MS<12000);
int32_t rpm=0;
const char *good[]={"MOTOR TEST MECH RUN POS 500","MOTOR TEST MECH RUN POS 600",
 "MOTOR TEST MECH RUN POS 700","MOTOR TEST MECH RUN POS 800"};
for(int i=0;i<4;i++)assert(Fcal_Parse(good[i],&rpm) && rpm==500+i*100);
const char *bad[]={"START","MOTOR TEST MECH RUN POS 1000","MOTOR TEST MECH RUN POS 801",
 "MOTOR TEST MECH RUN NEG 800","MOTOR TEST MECH RUN POS 240","MOTOR TEST MECH RUN POS 800x"};
for(int i=0;i<6;i++)assert(!Fcal_Parse(bad[i],&rpm));
for(int target=500;target<=800;target+=100){
 SpeedScurve s;SpeedScurve_Reset(&s,0);float travel=0;
 for(int ms=0;ms<10500;ms++){
  float speed=SpeedScurve_Step(&s,ms<5000?(float)target:0,.001f);
  assert(fabsf(s.acceleration_rpm_s)<=200.01f);
  /* Existing float integrator has sub-0.1rpm rounding before endpoint snap.
   * This numeric assertion is not a motor safety threshold. */
  if (!(speed>=-.1f && speed<=(float)target+.1f)) {
   fprintf(stderr,"target=%d ms=%d speed=%f accel=%f\n",target,ms,speed,s.acceleration_rpm_s);return 1;
  }
  travel+=fabsf(speed)*6*.001f;
  if(ms==4500)assert(fabsf(speed-target)<.01f);
 }
 assert(fabsf(s.speed_rpm)<.01f && fabsf(s.acceleration_rpm_s)<.01f);
 assert(travel<30000 && fabsf(travel-30*target)<10);
}
return 0;}
'''
        exe=ROOT/'tmp/mechanical-high-command-host.exe'
        p=subprocess.run([str(compiler.GCC),'-std=c11','-Os','-Wall','-Wextra','-Werror',
            '-I',str(ROOT/'firmware_common'),'-x','c','-',str(ROOT/'firmware_common/speed_scurve.c'),
            '-o',str(exe)],input=code,text=True,capture_output=True)
        self.assertEqual(p.returncode,0,p.stdout+p.stderr)
        p=subprocess.run([str(exe)],text=True,capture_output=True)
        self.assertEqual(p.returncode,0,p.stdout+p.stderr)

    def test_control_math_pipeline_and_driver_objects_unchanged(self):
        old=expanded('a','MechanicalIdentificationMotionCandidate')
        new=expanded('a','MechanicalIdentificationHighSpeedCandidate')
        for name in ('FOC_CurrentLoopStep','ProtectedLoop_AdcIrq','ProtectedLoop_PwmEntry',
            'ProtectedLoop_SetDuty','ProtectedLoop_TimerHealthy','ProtectedLoop_GuardIrqBody',
            'PowerStage_Enable','PowerStage_Disable','Encoder_ElectricalAngleRad','MotorControl_SetIq',
            'LatestOriginal_Admit'):
            self.assertEqual(function(old,name),function(new,name),name)
        setter=function(new,'MotorControl_SetSpeed')
        self.assertIn('800.0f',setter)
        self.assertIn('1000U',new)
        task=function(new,'TighteningTask')
        self.assertIn('encoder_position_deg-s->start_angle',task)
        self.assertIn('30000U',task)
        self.assertIn('10500U',task)
        self.assertEqual(task.count('CCER='),0)
        for name in ('stm32g4xx_it.c.obj','foc_adc_timing_stm32.c.obj','as5047p_dma_stm32.c.obj',
                     'foc_zero_robust.c.obj','tightening_intent_fsm.c.obj','mechanical_identification.c.obj'):
            a=ROOT/'foc2_app_a/build/MechanicalIdentificationMotionCandidate'
            b=ROOT/'foc2_app_a/build/MechanicalIdentificationHighSpeedCandidate'
            self.assertEqual(next(a.rglob(name)).read_bytes(),next(b.rglob(name)).read_bytes(),name)

    def test_warning_set_not_increased(self):
        warnings=[]
        for preset in ('MechanicalIdentificationMotionCandidate','MechanicalIdentificationHighSpeedCandidate'):
            directory=ROOT/'foc2_app_a/build'/preset
            cmd=next(c['command'] for c in json.loads((directory/'compile_commands.json').read_text()) if c['file'].endswith('/Core/Src/main.c'))
            p=subprocess.run(re.sub(r' -o \S+ -c ',' -fsyntax-only ',cmd),cwd=directory,capture_output=True,text=True)
            self.assertEqual(p.returncode,0,p.stdout+p.stderr)
            warnings.append(set(re.findall(r'warning: (.*)',p.stderr)))
        self.assertEqual(*warnings)

    def test_positive_only_batch_cannot_claim_full_model_qualification(self):
        # sign(omega) and intercept are identical for positive-only windows.
        points=[dict(alpha=(i%9)-4,omega=50.+i,direction=1,dt_s=.064,iq=.2+i*.001) for i in range(50)]
        with self.assertRaisesRegex(ValueError,'RANK_DEFICIENT'):low.analysis.solve(points)


if __name__=='__main__':unittest.main()
