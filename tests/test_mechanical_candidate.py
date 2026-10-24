import hashlib
import json
from pathlib import Path
import re
import subprocess
import unittest
from test_torque_chain import ROOT,function
from test_torque350_five_second import expanded


class CandidateTests(unittest.TestCase):
    def test_selected_half_flux_and_diagnostic_isolation(self):
        for preset,diag in (('TighteningBemfHalfCandidate',False),('MechanicalIdentificationCandidate',True)):
            directory=ROOT/'foc2_app_a/build'/preset
            cmd=next(c['command'] for c in json.loads((directory/'compile_commands.json').read_text()) if c['file'].endswith('/Core/Src/main.c'))
            for define in ('FOC_BEMF_PSI_WB=0.00034866f','FOC_BEMF_ENABLED_DEFAULT=1',
                'SPEED_ACCEL_FF_KA_A_PER_RPM_S=0.000046875f','SPEED_FRICTION_I_A=0.105f',
                'FOC_CURRENT_PI_IDENTIFIED_ENABLE=1','FOC_SPEED_PI_ANTI_WINDUP=1',
                'FOC_ONE_CYCLE_PWM_PIPELINE=1','FOC_PWM_PIPELINE_CLOSED_LOOP=1'):
                self.assertIn('-D'+define+' ',cmd)
            self.assertEqual('-DFOC_MECHANICAL_IDENT_DIAG=1 ' in cmd,diag)
            for flag in ('FOC_BEMF_GAIN_DIAG','FOC_KA_SYNC_DIAG','FOC_KA_FULL_DIAG',
                'FOC_ACCEL_FF_AUDIT','FOC_KA_IDENT_DIAG','FOC_PSI_IDENT_DIAG','FOC_CURRENT_STEP_AB_DIAG'):
                self.assertNotIn('-D'+flag,cmd)
            self.assertLess((directory/'foc2.bin').stat().st_size,229376)
        self.assertNotIn('FOC_MECHANICAL_IDENT_DIAG',(ROOT/'foc2_app_b/CMakeLists.txt').read_text())

    def test_control_tokens_unchanged_except_passive_publication_and_capture(self):
        normal=expanded('a','TighteningBemfHalfCandidate');diag=expanded('a','MechanicalIdentificationCandidate')
        for name in ('ProtectedLoop_AdcIrq','ProtectedLoop_PwmEntry','ProtectedLoop_SetDuty',
            'ProtectedLoop_TimerHealthy','ProtectedLoop_GuardIrqBody','PowerStage_Enable',
            'PowerStage_Disable','Encoder_ElectricalAngleRad',
            'TighteningTask','MotorControl_SetIq','MotorControl_SetSpeed','Bemf_Command'):
            self.assertEqual(function(normal,name),function(diag,name),name)
        norm=lambda s:re.sub(r'\s+',' ',s).strip()
        control=function(diag,'FOC_CurrentLoopStep')
        start=control.index('uint32_t mechanical_begin=')
        end=control.index('foc_vd_V = vd;',start)
        self.assertEqual(norm(function(normal,'FOC_CurrentLoopStep')),norm(control[:start]+control[end:]))
        for name in ('FOC_EncoderSpeedUpdate','MotorControlTask'):
            control=function(diag,name)
            if 'MechanicalCurrent mechanical_sample;' in control:
                start=control.index('MechanicalCurrent mechanical_sample;')
                end=control.index('SpeedFriction_Observe',start)
                hook_end=control.index('&mechanical_sample,mechanical_valid);',start)+len('&mechanical_sample,mechanical_valid);')
                self.assertLess(hook_end,end)
                control=control[:start]+control[hook_end:]
            self.assertEqual(norm(function(normal,name)),norm(control),name)

    def test_driver_objects_and_historical_images_preserved(self):
        a=ROOT/'foc2_app_a/build/TighteningBemfHalfCandidate'
        b=ROOT/'foc2_app_a/build/MechanicalIdentificationCandidate'
        for name in ('stm32g4xx_it.c.obj','foc_adc_timing_stm32.c.obj','as5047p_dma_stm32.c.obj',
                     'foc_zero_robust.c.obj','tightening_intent_fsm.c.obj'):
            self.assertEqual(next(a.rglob(name)).read_bytes(),next(b.rglob(name)).read_bytes(),name)
        for path,sha in (
            ('foc2_app_a/build/TighteningKa025Candidate/foc2.bin','4236aa0f7234b43bb12b6254fab0c75b34e59fc7ad8261be808f5a4b9054400a'),
            ('foc2_app_b/build/FrictionBUnchanged/foc2.bin','7ebdb56408baaa6c213c5dabe236250be673ed5a5c1345dfe64861d1e98dd366')):
            self.assertEqual(hashlib.sha256((ROOT/path).read_bytes()).hexdigest(),sha)
        source=(ROOT/'firmware_common/mechanical_dob_shadow.h').read_text()
        for name in ('foc_iq_ref_A','TIM1','PWM_SetDuty','speed_integrator_A'):
            self.assertNotIn(name,source)

    def test_new_build_warning_set_unchanged(self):
        warnings=[]
        for preset in ('TighteningBemfHalfCandidate','MechanicalIdentificationCandidate'):
            directory=ROOT/'foc2_app_a/build'/preset
            cmd=next(c['command'] for c in json.loads((directory/'compile_commands.json').read_text()) if c['file'].endswith('/Core/Src/main.c'))
            p=subprocess.run(re.sub(r' -o \S+ -c ',' -fsyntax-only ',cmd),cwd=directory,capture_output=True,text=True)
            self.assertEqual(p.returncode,0,p.stdout+p.stderr)
            warnings.append(set(re.findall(r'warning: (.*)',p.stderr)))
        self.assertEqual(*warnings)


if __name__=='__main__':unittest.main()
