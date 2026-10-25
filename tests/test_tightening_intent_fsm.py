"""Run the real C process core and backend contract; never hardware."""

from app_source_view import read_app_source
import hashlib
import json
from pathlib import Path
import re
import subprocess
import unittest
from test_torque_chain import GCC,FROZEN,function
from test_torque350_five_second import expanded

ROOT=Path(__file__).resolve().parents[1]
GXX=str(Path(GCC).with_name('g++.exe'))


class IntentFsmTests(unittest.TestCase):
    def test_compiled_process_and_port_all_scenarios_Os_O2(self):
        out=ROOT/'tests/intent_fsm_build'; out.mkdir(exist_ok=True)
        for opt in ('-Os','-O2'):
            objects=[]
            for source in ('firmware_common/tightening_intent_fsm.c','tests/tightening_intent_fsm_host.c'):
                obj=out/(Path(source).stem+opt+'.obj'); objects.append(str(obj))
                p=subprocess.run([GCC,'-std=c11',opt,'-Wall','-Wextra','-Werror',
                    '-I',str(ROOT/'firmware_common'),'-c',str(ROOT/source),'-o',str(obj)],capture_output=True,text=True)
                self.assertEqual(p.returncode,0,p.stdout+p.stderr)
            obj=out/('params'+opt+'.obj'); objects.append(str(obj))
            p=subprocess.run([GXX,'-std=c++17',opt,'-Wall','-Wextra','-Werror',
                '-I',str(ROOT/'firmware_common'),'-c',str(ROOT/'firmware_common/tighten_params.cpp'),'-o',str(obj)],
                capture_output=True,text=True)
            self.assertEqual(p.returncode,0,p.stdout+p.stderr)
            exe=out/('fsm'+opt+'.exe')
            p=subprocess.run([GXX,*objects,'-o',str(exe)],capture_output=True,text=True)
            self.assertEqual(p.returncode,0,p.stdout+p.stderr)
            p=subprocess.run([str(exe)],capture_output=True,text=True)
            self.assertEqual(p.returncode,0,p.stdout+p.stderr)

    def test_core_has_no_hal_controller_pwm_rtos_or_formatting(self):
        source=(ROOT/'firmware_common/tightening_intent_fsm.c').read_text()
        for forbidden in ('HAL_','TIM1','CCR','MotorControl_','integrator_A','printf','UART_',
                          'xTask','__disable_irq','FocCurrentPi','SpeedBrakeTrack'):
            self.assertNotIn(forbidden,source)
        self.assertEqual(source.count('s->previous_state=s->state; s->state=next;'),1)
        self.assertNotIn('FOC_',source)

    def test_hooks_reserved_identity_only_and_port_fails_closed(self):
        core=(ROOT/'firmware_common/control_intent.h').read_text()
        for hook in ('trajectory_generator','friction_feedforward','acceleration_feedforward',
                     'speed_anti_windup','dq_decoupling','dob'):
            self.assertIn('(*'+hook+')',core)
        binding=(ROOT/'firmware_common/tightening_intent_binding.inc').read_text()
        self.assertIn('ControlIntent_Passthrough(intent_fsm.intent)',binding)
        for forbidden in ('speed_integrator_A','foc_int_d_V =','TIM1->','CCR','SpeedBrakeTrack_'):
            self.assertNotIn(forbidden,binding)
        self.assertIn('IntentPort_Stop(NULL); MotorControl_SetIdle();',binding)

    def test_candidate_default_off_and_production_backend_frozen(self):
        for slot in 'ab':
            cm=(ROOT/f'foc2_app_{slot}/CMakeLists.txt').read_text()
            self.assertRegex(cm,r'option\(FOC_INTENT_FSM_CANDIDATE [^\n]+ OFF\)')
            a=expanded(slot,'RundownGuardTrial')
            b=expanded(slot,'TighteningIntentCandidate')
            for name in FROZEN+('MotorControl_SetSpeed','MotorControl_SetIq',
                    'Encoder_ElectricalAngleRad','FocFp_PushRawSafety','FocOcConfirm_Push',
                    'FocFeedbackSafety_Push','ProtectedLoop_GuardIrqBody','LatestOriginal_Admit'):
                self.assertEqual(function(a,name),function(b,name),name)
            for basename in ('foc_adc_timing_stm32.c.obj','stm32g4xx_it.c.obj'):
                hashes=[hashlib.sha256(next((ROOT/f'foc2_app_{slot}/build/{p}').rglob(basename)).read_bytes()).hexdigest()
                    for p in ('RundownGuardTrial','TighteningIntentCandidate')]
                self.assertEqual(*hashes,basename)

    def test_protocol_compatibility_and_required_debug_fields(self):
        binding=(ROOT/'firmware_common/tightening_intent_binding.inc').read_text()
        for field in ('FSM_STATE','PREV_STATE','STATE_TIME_MS','RUNDOWN_ARMED','CONTACT_PENDING',
                      'CONTACT_CONFIRMED','MOTION_TRAVEL_DEG','SPEED_TARGET','IQ_LIMIT',
                      'CONTROL_MODE','OUTCOME','FAULT_REASON'):
            self.assertIn(field+'=',binding)
        for slot in 'ab':
            src=read_app_source(ROOT/f'foc2_app_{slot}/Core/Src/main.c')
            self.assertIn('MotorJob_HandleUartStart(request_id);',src)
            self.assertIn('MotorJob_QueueStop(request_id);',src)
            self.assertIn('OK STATUS STAGE=',src)
            self.assertIn('#include "tightening_intent_binding.inc"',src)
            candidate=expanded(slot,'TighteningIntentCandidate')
            self.assertEqual(candidate.count('COMMAND-DRIVEN SINGLE-CYCLE MODE'),0)
            self.assertIn('INTENT_FSM_CANDIDATE; manual START only',candidate)

    def test_precheck_exception_preserves_every_existing_health_gate(self):
        for slot in 'ab':
            a=function(expanded(slot,'RundownGuardTrial'),'ProtectedLoop_Ready')
            b=function(expanded(slot,'TighteningIntentCandidate'),'ProtectedLoop_Ready')
            b=b.replace('(!Tightening_IsBusy() || TighteningIntent_PrecheckOnly())','!Tightening_IsBusy()')
            self.assertEqual(re.sub(r'\s+','',a),re.sub(r'\s+','',b))
        binding=(ROOT/'firmware_common/tightening_intent_binding.inc').read_text()
        predicate=function(binding,'TighteningIntent_PrecheckOnly')
        for token in ('state==TF_PRECHECK','control_mode==CONTROL_OFF',
                      '!intent_fsm.intent.enable_current_loop','!intent_fsm.intent.enable_speed_loop',
                      '!intent_fsm.intent.enable_position_loop'):
            self.assertIn(token,predicate)
        self.assertIn('stop_req=tightening_stop_request_id;',binding)
        self.assertIn('STOPPED START_REQ=',binding)

    def test_actual_stop_publication_is_atomic_to_task_and_still_closes_power(self):
        source=(ROOT/'firmware_common/motor_job_port.inc').read_text()
        body=function(source,'MotorJob_QueueStop')
        code='''#include <assert.h>
#include <stdint.h>
#define FOC_INTENT_FSM_CANDIDATE 1
#define FOC_LATEST_ORIGINAL_FSM 1
static unsigned mask,closed,tightening_stop_request,tightening_stop_request_id;
static void enter(void) {assert(!mask); mask=1;}
static void leave(void) {assert(mask && closed && tightening_stop_request && tightening_stop_request_id==78); mask=0;}
#define taskENTER_CRITICAL() enter()
#define taskEXIT_CRITICAL() leave()
#define __DMB() ((void)0)
static void ProtectedLoop_Stop(void) {assert(mask); closed=1;}
'''
        code+='static void '+body+'\nint main(void) {MotorJob_QueueStop(78); assert(!mask && closed); return 0;}\n'
        exe=ROOT/'tests/intent_fsm_build/stop.exe'
        p=subprocess.run([GCC,'-std=c11','-O2','-Wall','-Wextra','-Werror','-x','c','-',
            '-o',str(exe)],input=code,capture_output=True,text=True)
        self.assertEqual(p.returncode,0,p.stdout+p.stderr)
        p=subprocess.run([str(exe)],capture_output=True,text=True)
        self.assertEqual(p.returncode,0,p.stdout+p.stderr)


if __name__=='__main__': unittest.main()
