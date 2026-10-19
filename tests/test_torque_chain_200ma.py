"""Explicit positive-only 200mA preparation, never accesses hardware."""
import json
from pathlib import Path
import re
import subprocess
import sys
import unittest
from test_torque_chain_100ma import capture
from test_torque_chain import FROZEN, function, GCC

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
import torque_chain_decode as decoder


def capture200(angles):
    data=capture(angles,1)
    for i in range(len(angles)):
        values=list(decoder.startup.FRAME.unpack_from(data,i*124))
        values[10]=.2; values[12]=.2
        decoder.startup.FRAME.pack_into(data,i*124,*values)
    return data


class Torque200Tests(unittest.TestCase):
    def test_real_production_setter_and_outer_iq_clamp(self):
        # Do not use the admission harness's fake setter: it missed the 150mA
        # clamp. Compile the actual setter AND actual outer IQ assignment.
        out=ROOT/'tests/torque_chain_build'; out.mkdir(exist_ok=True)
        for slot in 'ab':
            source=(ROOT/f'foc2_app_{slot}/Core/Src/main.c').read_text()
            limit=re.search(r'^#define MOTOR_DIRECT_IQ_LIMIT_A\s+(\S+)',source,re.M).group(1)
            self.assertEqual(limit,'0.20f')
            outer=function(source,'FOC_EncoderSpeedUpdate')
            assign=re.search(r'foc_iq_ref_A\s*=\s*ClampFloat\(motor_iq_command_A,\s*'
                             r'-MOTOR_DIRECT_IQ_LIMIT_A,\s*MOTOR_DIRECT_IQ_LIMIT_A\);',outer).group(0)
            code='''#include <assert.h>
#include <math.h>
#define FOC_ONE_CYCLE_PWM_PIPELINE 1
#define MOTOR_MODE_IDLE 0
#define MOTOR_MODE_IQ 3
static unsigned motor_control_mode, invalidations;
static float motor_iq_command_A, motor_speed_command_rpm, foc_iq_ref_A;
static unsigned motor_position_active_hold;
static void ProtectedLoop_PwmInvalidate(void) {++invalidations;}
'''+f'#define MOTOR_DIRECT_IQ_LIMIT_A {limit}\n'
            code+='static float '+function(source,'ClampFloat')+'\n'
            code+='static void '+function(source,'MotorControl_SetIq')+'\n'
            code+='static void apply_outer_iq(void) {'+assign+'}\n'
            code+='''int main(void) {
  const float request[]={0.2f,-0.2f,0.1f,-0.1f,1.0f,-1.0f,0.0f};
  const float expected[]={0.2f,-0.2f,0.1f,-0.1f,0.2f,-0.2f,0.0f};
  for(unsigned i=0;i<7;++i) {
    motor_control_mode=MOTOR_MODE_IDLE; motor_position_active_hold=1;
    motor_speed_command_rpm=20; MotorControl_SetIq(request[i]);
    assert(motor_control_mode==MOTOR_MODE_IQ);
    assert(!motor_position_active_hold && motor_speed_command_rpm==0);
    assert(fabsf(motor_iq_command_A-expected[i])<1e-7f);
    apply_outer_iq(); assert(fabsf(foc_iq_ref_A-expected[i])<1e-7f);
  }
  assert(invalidations==7); return 0;
}'''
            for opt in ('-Os','-O2'):
                exe=out/f'real_setter_{slot}{opt}.exe'
                r=subprocess.run([GCC,'-std=c11',opt,'-Wall','-Wextra','-Werror',
                                  '-x','c','-','-o',str(exe)],input=code,capture_output=True,text=True)
                self.assertEqual(r.returncode,0,r.stdout+r.stderr)
                r=subprocess.run([str(exe)],capture_output=True,text=True)
                self.assertEqual(r.returncode,0,r.stdout+r.stderr)

    def test_positive_stats_and_no_negative_or_offset(self):
        report=decoder.analyze(capture200([0,.5,1,.8]),1,0,200)
        self.assertEqual(report['Iq_command_A'],.2)
        self.assertEqual(report['IdRef_A'],0)
        self.assertAlmostEqual(report['statistics']['mean_Iq_A'],.2,places=6)
        self.assertAlmostEqual(report['statistics']['net_mechanical_travel_deg'],.8,places=6)
        self.assertGreater(report['statistics']['opposite_direction_intervals'],0)
        self.assertFalse(report['automatic_sweep'])
        for sign,offset,iq in ((-1,0,200),(1,5,200),(1,0,201),(1,0,400)):
            with self.assertRaises(ValueError): decoder.analyze(capture200([0,1]),sign,offset,iq)

    def test_explicit_preset_default_does_not_increase(self):
        for slot in 'ab':
            presets=json.loads((ROOT/f'foc2_app_{slot}/CMakePresets.json').read_text())
            p=next(x for x in presets['configurePresets'] if x['name']=='TorqueChain200mADiagnostic')
            self.assertEqual(p['cacheVariables']['FOC_TORQUE_CHAIN_IQ_MA'],'200')
            text=(ROOT/f'foc2_app_{slot}/CMakeLists.txt').read_text()
            self.assertIn('set(FOC_TORQUE_CHAIN_IQ_MA "100" CACHE',text)
            self.assertIn('profiles only" OFF)',text)

    def test_100_and_200_control_and_irq_objects_unchanged(self):
        for slot in 'ab':
            expanded=[]
            for preset in ('TorqueChain100mADiagnostic','TorqueChain200mADirectLimitDiagnostic'):
                base=ROOT/f'foc2_app_{slot}/build/{preset}'
                commands=json.loads((base/'compile_commands.json').read_text())
                command=next(x['command'] for x in commands if x['file'].endswith('/Core/Src/main.c'))
                result=subprocess.run(re.sub(r' -o \S+ -c ',' -E -P ',command),cwd=base,
                    capture_output=True,text=True,check=True)
                expanded.append(result.stdout)
            for name in FROZEN+('MotorControl_SetIq','FocFp_PushRawSafety','FocOcConfirm_Push',
                               'FocFeedbackSafety_Push','ProtectedLoop_GuardIrqBody'):
                self.assertEqual(function(expanded[0],name),function(expanded[1],name),name)
            for basename in ('foc_adc_timing_stm32.c.obj','stm32g4xx_it.c.obj'):
                objects=[next((ROOT/f'foc2_app_{slot}/build/{p}').rglob(basename)).read_bytes()
                         for p in ('TorqueChain100mADiagnostic','TorqueChain200mADirectLimitDiagnostic')]
                self.assertEqual(objects[0],objects[1],basename)


if __name__=='__main__': unittest.main()
