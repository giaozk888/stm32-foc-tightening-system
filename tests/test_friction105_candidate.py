"""Exploratory 105mA Coulomb A: parameter-only candidate, no device access."""
import hashlib
import json
import re
import unittest
import test_speed_friction_compensation as original
from test_torque_chain import FROZEN, function
from test_torque350_five_second import expanded

ON = 'Tightening240rpmFriction105OnCandidate'
OFF = 'Tightening240rpmFriction105OffCandidate'
OLD = 'Tightening240rpmFrictionOnCandidate'
ROOT = original.ROOT


class Friction105Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.out = ROOT/'tests/speed_friction105_build'
        cls.out.mkdir(exist_ok=True)

    compile_run = original.FrictionTests.compile_run

    def test_signed_105ma_deadband_combined_clamp_and_aw(self):
        self.compile_run(r'''
#include <assert.h>
#include <math.h>
#include "speed_friction_compensation.h"
int main(void) {
 for(int sign=-1;sign<=1;sign+=2) {
  float s=(float)sign;
  SpeedFrictionResult on=SpeedFriction_Apply(0,0,s*.1f,s*200,
      .0001875f,s*240,.105f,2,.5f,.5f,0,1,1);
  assert(fabsf(on.iq_fric_a-s*.105f)<1e-6f);
  assert(fabsf(on.speed.iq_ref_a-s*.2425f)<1e-6f);
  SpeedFrictionResult off=SpeedFriction_Apply(0,0,s*.1f,s*200,
      .0001875f,s*240,.105f,2,.5f,.5f,0,1,0);
  SpeedAccelFfResult base=SpeedAccelFf_Apply(0,0,s*.1f,s*200,
      .0001875f,.5f,.5f,0,1);
  assert(off.iq_fric_a==0 && off.speed.iq_ref_a==base.iq_ref_a);
  assert(off.speed.integral_a==base.integral_a);
  for(int i=0;i<300;++i) {
   float candidate=s*(float)i/200;
   SpeedFrictionResult r=SpeedFriction_Apply(0,candidate,s*.2f,s*200,
       .0001875f,s*240,.105f,2,.5f,.5f,0,1,1);
   assert(fabsf(r.speed.iq_ref_a)<=.5f);
   assert(fabsf(r.speed.integral_a)<=.157501f);
  }
  SpeedFrictionResult zero=SpeedFriction_Apply(0,0,0,0,
      .0001875f,s*2,.105f,2,.5f,.5f,0,1,1);
  assert(zero.iq_fric_a==0 && zero.speed.iq_ref_a==0);
 }
 return 0;
}
''', 'parameter')

    def test_all_control_and_protection_functions_unchanged(self):
        before=expanded('a',OLD)
        after=expanded('a',ON)
        for name in set(FROZEN+('TighteningTask','FOC_EncoderSpeedUpdate',
            'SpeedPiAntiWindup_Apply','SpeedBumpless_Apply','MotorControl_SetSpeed',
            'MotorControl_SetIq','MotorControl_SetIdle','PowerStage_Disable',
            'Encoder_ElectricalAngleRad','FocOcConfirm_Push','FocFeedbackSafety_Push')):
            a=function(before,name)
            b=function(after,name)
            # Sole intended compiled change: the existing Coulomb call parameter.
            if name=='FOC_EncoderSpeedUpdate':
                self.assertIn('0.105f',b)
                b=b.replace('0.105f','0.20f')
            self.assertEqual(re.sub(r'\s+','',a),re.sub(r'\s+','',b),name)

    def test_build_flags_tokenized_logs_and_old_b_preserved(self):
        for name,enabled in ((ON,1),(OFF,0)):
            folder=ROOT/'foc2_app_a/build'/name
            commands=json.loads((folder/'compile_commands.json').read_text())
            cmd=next(x['command'] for x in commands if x['file'].endswith('/Core/Src/main.c'))
            for flag in ('-DSPEED_FRICTION_I_A=0.105f',
                         '-DSPEED_FRICTION_DEADBAND_RPM=2.0f',
                         '-DFOC_FRICTION_ENABLED_DEFAULT='+str(enabled)):
                self.assertIn(flag,cmd)
            self.assertNotIn('-DFOC_FRICTION_CALIBRATION_DIAG',cmd)
            self.assertIn('firmware_common/pw_log_tokenized_override',cmd)
            data=(folder/'foc2.bin').read_bytes()
            self.assertIn(b'SPEED_CTRL=FR1',data)
            self.assertNotIn(b'FRC C seq=',data)
        for path,sha in (
          ('foc2_app_a/build/'+OLD+'/foc2.bin',
           'c8c7a7e9e0753e6d39aadaddcd038df3c3f943aa0f3d167397662ac615d015f8'),
          ('foc2_app_b/build/FrictionBUnchanged/foc2.bin',
           '7ebdb56408baaa6c213c5dabe236250be673ed5a5c1345dfe64861d1e98dd366')):
            self.assertEqual(hashlib.sha256((ROOT/path).read_bytes()).hexdigest(),sha)


if __name__=='__main__':
    unittest.main()
