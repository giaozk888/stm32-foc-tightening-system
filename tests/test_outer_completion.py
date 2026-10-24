import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import unittest
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
import current_pi_compare as compiler
from test_torque_chain import function
from test_torque350_five_second import expanded
OLD='MechanicalHighSpeedEncoderFixCandidate'
NEW='MechanicalOuterCompletionCandidate'


class OuterCompletionTests(unittest.TestCase):
    def test_control_math_unchanged_and_only_observations_deferred(self):
        old=expanded('a',OLD);new=expanded('a',NEW)
        for name in ('FOC_CurrentLoopStep','ProtectedLoop_HealthCaptured','ProtectedLoop_PwmEntry',
            'ProtectedLoop_PwmStage','ProtectedLoop_GuardIrqBody','PowerStage_Enable','PowerStage_Disable',
            'Encoder_ElectricalAngleRad','MotorControl_SetIq','MotorControl_SetSpeed',
            'LatestOriginal_Admit','TighteningTask'):
            self.assertEqual(function(old,name),function(new,name),name)
        a=function(old,'FOC_EncoderSpeedUpdate');b=function(new,'FOC_EncoderSpeedUpdate')
        start=b.index('outer_observation.pending=0U;')
        end=b.index('if (consumed == 0) return HAL_BUSY;',start)
        b=b[:start]+b[end:]
        start_a=a.index('SpeedAccelFf_Observe(&speed_accel_ff_stats')
        end_a=a.index('FrictionCalibration_Observe(dt_meas);',start_a)+len('FrictionCalibration_Observe(dt_meas);')
        start_b=b.index('outer_observation.valid=Mechanical_TryRead')
        end_b=b.index('outer_observation.pending=1U;',start_b)+len('outer_observation.pending=1U;')
        b=b[:start_b]+a[start_a:end_a]+b[end_b:]
        norm=lambda s:re.sub(r'\s+','',s)
        self.assertEqual(norm(a),norm(b))
        flush=function(new,'OuterObservation_Flush')
        for token in ('DmaAcknowledgeControl','foc_iq_ref_A =','TIM1','MotorControl_Set','SpeedScurve_Step'):
            self.assertNotIn(token,flush)
        task=function(new,'ProtectedLoop_TaskService')
        self.assertLess(task.index('FOC_EncoderSpeedUpdate'),task.index('cl_session.outer_us='))
        self.assertLess(task.index('cl_session.outer_us='),task.index('OuterObservation_Flush'))
        for file in ('as5047p_dma_stm32.c.obj','stm32g4xx_it.c.obj','foc_adc_timing_stm32.c.obj',
            'foc_zero_robust.c.obj','tightening_intent_fsm.c.obj','mechanical_identification.c.obj'):
            self.assertEqual(next((ROOT/'foc2_app_a/build'/OLD).rglob(file)).read_bytes(),
                next((ROOT/'foc2_app_a/build'/NEW).rglob(file)).read_bytes(),file)

    def test_actual_service_and_flush_commit_before_statistics_no_busy_ack(self):
        source=expanded('a',NEW)
        flush='static void '+function(source,'OuterObservation_Flush')
        task=function(source,'ProtectedLoop_TaskService')
        task='static void '+task[:task.index('if (update==HAL_BUSY) return;')+len('if (update==HAL_BUSY) return;')]+'\n}'
        raw=(ROOT/'foc2_app_a/Core/Src/main.c').read_text()
        start=raw.index('static struct {',raw.index('static OuterCompletionTrace outer_completion_trace;'))
        pending=raw[start:raw.index('} outer_observation;',start)+len('} outer_observation;')]
        code=r'''
#include <assert.h>
#include <stdint.h>
#include "mechanical_identification.h"
#include "speed_friction_compensation.h"
#include "outer_completion_trace.h"
typedef enum {HAL_OK=0,HAL_ERROR=1,HAL_BUSY=2} HAL_StatusTypeDef;
static OuterCompletionTrace outer_completion_trace;
''' + pending + r'''
static unsigned cl_armed=1,adc_fault,foc_fault,cl_outer_n,acks,angle_published,statistics_calls;
static unsigned periodic=1,forced_status,inject_observer_fault;
static float foc_iq_ref_A;
static uint32_t now_us=1000;
static struct {uint32_t outer_us;} cl_session={900};
static SpeedAccelFfStats speed_accel_ff_stats;
static SpeedAccelFfFrame speed_accel_ff_frame;
static MechanicalCapture mechanical_capture;
static SpeedFrictionStats speed_friction_stats;
static SpeedFrictionFrame speed_friction_frame;
static unsigned speed_friction_enabled=1,gates_off;
#define CL_BAD_ENCODER 32U
static uint32_t AS5047P_DmaNowUs(void){return now_us;}
static void MotorControl_SetIdle(void){}
static int AS5047P_DmaIsPeriodic(void){return periodic;}
static void AS5047P_DmaStopPeriodic(void){periodic=0;}
static int AS5047P_DmaStartPeriodic(void){periodic=1;return 1;}
static void ProtectedLoop_EmergencyOff(unsigned flags){(void)flags;gates_off=1;cl_armed=0;}
static HAL_StatusTypeDef FOC_EncoderSpeedUpdate(float dt){
 (void)dt;
 if(forced_status)return (HAL_StatusTypeDef)forced_status;
 outer_observation.pending=1;outer_observation.current.seq=42;
 outer_observation.sample_us=1200;outer_observation.observed_us=1400;
 outer_observation.dt_s=.001f;outer_observation.dt_us=1000;
 outer_observation.delta=3;outer_observation.omega_rad_s=50;
 angle_published=1;++acks;now_us=1700;return HAL_OK;
}
static void assert_after_commit(void){
 assert(angle_published && acks==1 && cl_outer_n==1 && cl_session.outer_us==1700);
 ++statistics_calls;now_us+=20;
}
void SpeedAccelFf_Observe(SpeedAccelFfStats *s,const SpeedAccelFfFrame *f,float dt){
 (void)s;(void)f;(void)dt;assert_after_commit();
 if(inject_observer_fault){foc_fault=1;gates_off=1;cl_armed=0;
  outer_completion_trace.fault_phase=outer_completion_trace.current.phase;
  outer_completion_trace.frozen=1;}
}
void Mechanical_Observe(MechanicalCapture *s,uint32_t observed,uint32_t sample,uint32_t dt,
 int32_t delta,float omega,uint8_t sat,const MechanicalCurrent *c,uint8_t valid){
 (void)s;(void)sat;(void)valid;assert_after_commit();
 assert(observed==1400 && sample==1200 && dt==1000 && delta==3 && omega==50 && c->seq==42);
}
void SpeedFriction_Observe(SpeedFrictionStats *s,const SpeedFrictionFrame *f,float dt){
 (void)s;(void)f;(void)dt;assert_after_commit();
}
static void FrictionCalibration_Observe(float dt){(void)dt;assert_after_commit();}
''' + flush + task + r'''
static void reset(void){
 outer_completion_trace=(OuterCompletionTrace){0};outer_observation.pending=0;
 cl_armed=periodic=1;adc_fault=foc_fault=forced_status=0;
 acks=angle_published=cl_outer_n=statistics_calls=gates_off=inject_observer_fault=0;
 cl_session.outer_us=900;now_us=1000;
}
int main(void){
 reset();ProtectedLoop_TaskService();
 assert(acks==1 && statistics_calls==4 && !outer_observation.pending && !gates_off);
 assert(outer_completion_trace.current.commit_us==1700);
 assert(outer_completion_trace.current.phase==5 && outer_completion_trace.max_observe_us==80);
 /* No sample/invalid sample must NOT publish heartbeat or flush old payload. */
 reset();forced_status=HAL_BUSY;outer_observation.pending=1;ProtectedLoop_TaskService();
 assert(!acks && !cl_outer_n && !statistics_calls && !outer_observation.pending && cl_session.outer_us==900);
 reset();forced_status=HAL_ERROR;ProtectedLoop_TaskService();
 assert(!acks && !cl_outer_n && !statistics_calls && gates_off);
 /* Independent fault while observing remains OFF and freezes first phase. */
 reset();inject_observer_fault=1;ProtectedLoop_TaskService();
 assert(gates_off && outer_completion_trace.frozen && outer_completion_trace.fault_phase==4);
 assert(outer_completion_trace.current.phase==4);
 uint32_t saved=outer_completion_trace.current.entry_us;
 now_us+=1000;ProtectedLoop_TaskService();assert(outer_completion_trace.current.entry_us==saved);
 /* Trace time arithmetic tolerates microsecond wrap; no protection decisions. */
 OuterCompletionTrace t={0};OuterTrace_Enter(&t,0xfffffff0U,0);
 OuterTrace_Commit(&t,0x10U);assert(t.max_core_us==32);
 return 0;}
'''
        for opt in ('-Os','-O2'):
            exe=ROOT/'tmp'/('outer-completion-host'+opt+'.exe')
            p=subprocess.run([str(compiler.GCC),'-std=c11',opt,'-Wall','-Wextra','-Werror',
                '-I',str(ROOT/'firmware_common'),'-x','c','-','-o',str(exe)],input=code,text=True,capture_output=True)
            self.assertEqual(p.returncode,0,p.stdout+p.stderr)
            p=subprocess.run([str(exe)],text=True,capture_output=True)
            self.assertEqual(p.returncode,0,p.stdout+p.stderr)

    def test_first_fault_and_watchdogs_not_weakened(self):
        old=expanded('a',OLD);new=expanded('a',NEW)
        a=function(old,'FaultDiag_CapturePacked');b=function(new,'FaultDiag_CapturePacked')
        b=b.replace('outer_completion_trace.fault_phase=outer_completion_trace.current.phase;','').replace('outer_completion_trace.frozen=1U;','')
        self.assertEqual(re.sub(r'\s+','',a),re.sub(r'\s+','',b))
        self.assertIn('CL_OUTER_DEADLINE_US=2000U',new)
        for k,v in [('TRANSACTION',200),('SCHEDULE_LATE',200),('SAMPLE_MAX_AGE',1500),('CONTROL_WATCHDOG',2500)]:
            self.assertRegex((ROOT/'firmware_common/as5047p_timing_policy.h').read_text(),rf'AS_DMA_{k}_US\s+{v}U')
        self.assertNotIn('FOC_OUTER_OBSERVE_AFTER_ACK',(ROOT/'foc2_app_b/CMakeLists.txt').read_text())
        self.assertEqual(hashlib.sha256((ROOT/'foc2_app_a/build'/OLD/'foc2.bin').read_bytes()).hexdigest(),
            '212ebe9c5c3a8b09a29ed3279ac9c78c100ef80276dfc75de0439c982a7eb862')

    def test_warning_set_unchanged(self):
        sets=[]
        for preset in (OLD,NEW):
            directory=ROOT/'foc2_app_a/build'/preset
            cmd=next(c['command'] for c in json.loads((directory/'compile_commands.json').read_text()) if c['file'].endswith('/Core/Src/main.c'))
            p=subprocess.run(re.sub(r' -o \S+ -c ',' -fsyntax-only ',cmd),cwd=directory,capture_output=True,text=True)
            self.assertEqual(p.returncode,0,p.stdout+p.stderr)
            sets.append(set(re.findall(r'warning: (.*)',p.stderr)))
        self.assertEqual(*sets)


if __name__=='__main__':unittest.main()
