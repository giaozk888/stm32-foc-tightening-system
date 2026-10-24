"""High grid: real clamps/parser, frozen control/protection, no devices."""
import json
from pathlib import Path
import re
import subprocess
import sys
import unittest
from test_torque_chain import GCC,ROOT,FROZEN,function
from test_torque350_five_second import expanded
sys.path.insert(0,str(ROOT/'tools'))
import friction_high_speed_board as high
import friction_calibration_board as cal


class HighSpeedTests(unittest.TestCase):
    def test_real_parser_and_setspeed_do_not_clip_260_280_to_250(self):
        source=expanded('a','FrictionCalibrationHighSpeedDiagnostic')
        body=function(source,'MotorControl_SetSpeed')
        code=r'''
#include <assert.h>
#include <math.h>
#define FOC_FRICTION_HIGH_SPEED_GRID 1
#include "friction_calibration.h"
#define MOTOR_MODE_SPEED 2
static unsigned motor_control_mode,motor_position_active_hold;
static float motor_speed_command_rpm,motor_iq_command_A;
static float ClampFloat(float v,float lo,float hi){return v<lo?lo:v>hi?hi:v;}
static void ProtectedLoop_PwmInvalidate(void){}
'''+'static void '+body+r'''
int main(void){
 int32_t rpm=0;
 assert(Fcal_Parse("MOTOR TEST FCAL RUN POS 200",&rpm) && rpm==200);
 assert(Fcal_Parse("MOTOR TEST FCAL RUN POS 260",&rpm) && rpm==260);
 assert(Fcal_Parse("MOTOR TEST FCAL RUN NEG 280",&rpm) && rpm==-280);
 assert(!Fcal_Parse("MOTOR TEST FCAL RUN POS 300",&rpm));
 assert(!Fcal_Parse("MOTOR TEST FCAL RUN POS 40",&rpm));
 assert(!Fcal_Parse("MOTOR TEST FCAL RUN POS 250",&rpm));
 MotorControl_SetSpeed(260);assert(motor_speed_command_rpm==260);
 MotorControl_SetSpeed(280);assert(motor_speed_command_rpm==280);
 MotorControl_SetSpeed(-280);assert(motor_speed_command_rpm==-280);
 MotorControl_SetSpeed(300);assert(motor_speed_command_rpm==280);
 assert(motor_control_mode==MOTOR_MODE_SPEED && motor_iq_command_A==0);
 return 0;
}'''
        exe=ROOT/'tmp/friction-high-host.exe'
        p=subprocess.run([GCC,'-x','c','-','-std=c11','-O2','-Wall','-Wextra','-Werror',
            '-I',str(ROOT/'firmware_common'),'-o',str(exe)],input=code,text=True,capture_output=True)
        self.assertEqual(p.returncode,0,p.stdout+p.stderr)
        self.assertEqual(subprocess.run([str(exe)]).returncode,0)

    def test_frozen_fast_paths_and_exact_scope_of_new_limit(self):
        old=expanded('a','FrictionCalibrationDiagnostic')
        new=expanded('a','FrictionCalibrationHighSpeedDiagnostic')
        for name in FROZEN+('ProtectedLoop_Ready','FocFeedbackSafety_Push',
            'FocFp_PushRawSafety','SpeedBumpless_Apply','SpeedPiAntiWindup_Apply',
            'MotorControl_SetIdle','ProtectedLoop_HealthCaptured','TighteningTask'):
            a=function(old,name);b=function(new,name)
            if name=='FOC_EncoderSpeedUpdate':b=b.replace('280.0f','250.0f')
            self.assertEqual(re.sub(r'\s+','',a),re.sub(r'\s+','',b),name)
        for expected in ('CL_OVERSPEED_RPM=300','CL_MAX_US=12000000U'):
            self.assertIn(expected,re.sub(r'\s+','',new))
        self.assertIn('fabsf(encoder_speed_rpm) > 300.0f',new)

    def test_default_high_grid_files_only_and_original_b_pinned(self):
        p=subprocess.run([sys.executable,str(ROOT/'tools/friction_high_speed_board.py')],
            text=True,capture_output=True,timeout=15)
        self.assertEqual(p.returncode,0,p.stdout+p.stderr)
        self.assertIn('280',p.stdout);self.assertIn('OFFLINE PASS: no device access',p.stdout)
        self.assertNotIn(' 40,',p.stdout)

    def test_high_identity_and_immutable_old_diagnostic(self):
        self.assertEqual(len(high.image()),high.SIZE)
        self.assertEqual(high.POINTS,(200,240,260,280,-200,-240,-260,-280))
        self.assertEqual(cal.base.old.zero.digest((ROOT/'foc2_app_a/build/FrictionCalibrationDiagnostic/foc2.bin').read_bytes()),
                         high.OLD_CAL_SHA)


if __name__=='__main__':unittest.main()
