"""Normal A Ka selection and existing BEMF integration, files only."""
import hashlib
import json
import re
import subprocess
import unittest
from test_torque_chain import ROOT,FROZEN,function
from test_torque350_five_second import expanded

OFF='TighteningKa025Candidate'
ON='TighteningKa025BemfOnCandidate'

class Ka025BemfTests(unittest.TestCase):
    def test_normal_not_diagnostic_and_exact_parameters(self):
        for preset,enabled in ((OFF,0),(ON,1)):
            directory=ROOT/'foc2_app_a/build'/preset
            cmd=next(x['command'] for x in json.loads((directory/'compile_commands.json').read_text())
                     if x['file'].endswith('/Core/Src/main.c'))
            for define in ('SPEED_ACCEL_FF_KA_A_PER_RPM_S=0.000046875f',
                'FOC_BEMF_PSI_WB=0.00069732f','FOC_BEMF_ENABLED_DEFAULT='+str(enabled),
                'SPEED_FRICTION_I_A=0.105f','FOC_CURRENT_PI_IDENTIFIED_ENABLE=1',
                'FOC_SPEED_PI_ANTI_WINDUP=1','FOC_ONE_CYCLE_PWM_PIPELINE=1',
                'FOC_PWM_PIPELINE_CLOSED_LOOP=1','PW_LOG_STORE_CAPACITY=48'):
                self.assertIn('-D'+define+' ',cmd)
            for flag in ('FOC_KA_FULL_DIAG','FOC_KA_SYNC_DIAG','FOC_KA_IDENT_DIAG',
                'FOC_ACCEL_FF_AUDIT','FOC_STARTUP_TIMESTAMPS_DIAG','FOC_CURRENT_STEP_AB_DIAG',
                'FOC_PSI_IDENT','FOC_FAST_REJECT_COMPUTE_ONLY','FOC_DQ_DECOUPLING_CANDIDATE'):
                self.assertNotIn('-D'+flag,cmd)
            self.assertLess((directory/'foc2.bin').stat().st_size,229376)
            image=(directory/'foc2.bin').read_bytes()
            self.assertNotIn(b'MOTOR TEST FF GAIN ',image)
            for marker in (b'METHOD=TWO_SAMPLE',b'TRIP_MA=4000',b'TRAVEL=20000deg RAM only',
                           b'RUNDOWN240: RAM=240rpm TRIP=300rpm SAVE=OFF'):
                self.assertIn(marker,image)

    def test_only_ka_constant_and_bemf_initial_switch_changed(self):
        baseline=expanded('a','BemfFittedMemoryCandidate')
        off,on=expanded('a',OFF),expanded('a',ON)
        names=FROZEN+('Protocol_HandleLine','Protocol_PrintStatus','TighteningTask',
            'MotorControlTask','PowerStage_Disable','Encoder_ElectricalAngleRad',
            'MotorControl_SetSpeed','MotorControl_SetIq','StartupTask')
        for name in names:
            self.assertEqual(function(baseline,name).replace('0.0001875f','0.000046875f'),
                             function(off,name),name)
            self.assertEqual(function(off,name),function(on,name),name)
        self.assertRegex(off,r'bemf_enabled\s*=\s*0\s*;')
        self.assertRegex(on,r'bemf_enabled\s*=\s*1\s*;')
        f=function(off,'FOC_CurrentLoopStep')
        self.assertLess(f.index('FocBemf_Apply'),f.index('mag2 = vd * vd'))
        self.assertNotIn('printf',f)
        self.assertIn('encoder_omega_e_rad_s',f)

    def test_realtime_driver_objects_and_old_images_preserved(self):
        parent=ROOT/'foc2_app_a/build/BemfFittedMemoryCandidate'
        for name in ('stm32g4xx_it.c.obj','foc_adc_timing_stm32.c.obj',
                     'as5047p_dma_stm32.c.obj','foc_zero_robust.c.obj','tightening_intent_fsm.c.obj'):
            raw=next(parent.rglob(name)).read_bytes()
            for preset in (OFF,ON):
                self.assertEqual(raw,next((ROOT/'foc2_app_a/build'/preset).rglob(name)).read_bytes(),name)
        for path,sha in (
            ('foc2_app_a/build/Ka279ManualTrial/foc2.bin','7891e9ce9b2aec45b74019b5a63a908ff236bfbafb0c24caf693244d1a984c27'),
            ('foc2_app_b/build/TighteningCommonModeCandidate/foc2.bin','7ebdb56408baaa6c213c5dabe236250be673ed5a5c1345dfe64861d1e98dd366')):
            self.assertEqual(hashlib.sha256((ROOT/path).read_bytes()).hexdigest(),sha)

    def test_warning_set_matches_and_no_new_limit(self):
        warnings=[]
        for preset in ('BemfFittedMemoryCandidate',OFF,ON):
            directory=ROOT/'foc2_app_a/build'/preset
            cmd=next(x['command'] for x in json.loads((directory/'compile_commands.json').read_text())
                     if x['file'].endswith('/Core/Src/main.c'))
            p=subprocess.run(re.sub(r' -o \S+ -c ',' -fsyntax-only ',cmd),cwd=directory,
                             capture_output=True,text=True,check=True)
            warnings.append(set(re.findall(r'warning: (.*)',p.stderr)))
        self.assertEqual(warnings[0],warnings[1]);self.assertEqual(warnings[0],warnings[2])

if __name__=='__main__':unittest.main()
