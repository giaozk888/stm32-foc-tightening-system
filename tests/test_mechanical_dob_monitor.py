import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import unittest
from test_torque_chain import GCC,function
from test_torque350_five_second import expanded
ROOT=Path(__file__).resolve().parents[1]
OLD='MechanicalReadinessSnapshotCandidate'
NEW='MechanicalDobShadowCandidate'


class DobMonitorTests(unittest.TestCase):
    def test_native_matched_current_signed_disturbance_quality_warmup_stop_fault_and_wrap(self):
        code=r'''
#include <assert.h>
#include <math.h>
#include <stddef.h>
#include <string.h>
#include "mechanical_dob_monitor.h"
static MechanicalDobMonitor mon;
static uint32_t enc=1000,seq=20;
static void sample(float iq,float id,float w){
 MechanicalCurrent c={2,seq,enc-20,enc,id,iq,0};
 MechanicalDobMonitor_Observe(&mon,enc+20,enc,1000,w,0,&c,1);
 enc+=1000;seq+=20;
}
static float current(float w,float d){
 const MechanicalNormalizedModel *m=&mechanical_dob_identified_model;
 return m->b_over_kt*w+m->coulomb_over_kt*(w>0?1:-1)+m->bias_a+d;
}
static void reset(void){memset(&mon,0,sizeof mon);enc=1000;seq=20;MechanicalDobMonitor_Lifecycle(&mon,1,0);}
int main(void){
assert(sizeof mon==856 && sizeof(MechanicalDobMonitorFrame)==44);
assert(offsetof(MechanicalDobMonitor,frames)==28 && offsetof(MechanicalDobMonitor,current)==732);
assert(offsetof(MechanicalDobMonitor,version)==776 && offsetof(MechanicalDobMonitor,max_compute_us)==852);
const MechanicalNormalizedModel *m=&mechanical_dob_identified_model;
assert(fabsf(m->j_over_kt-.0003782906587f)<1e-10f);
assert(fabsf(m->b_over_kt-.001567686433f)<1e-9f);
assert(fabsf(m->coulomb_over_kt-.1194516824f)<1e-7f && m->qualified);
for(int sign=-1;sign<=1;sign+=2){
 reset();for(unsigned i=0;i<1500;i++)sample(current(50*sign,.02f*sign),.005f,50*sign);
 assert(mon.current.valid && fabsf(mon.current.disturbance_a-.02f*sign)<1e-5f);
 assert(mon.valid_samples>900 && mon.count>16 && mon.head<16);
 assert(mon.current.adc_source_us==mon.current.sample_us-20);
 MechanicalDobMonitorView v;assert(MechanicalDobMonitor_Read(&mon,&v));
 assert(v.running && v.current.valid && v.valid_samples==mon.valid_samples);
 mon.version|=1;assert(!MechanicalDobMonitor_Read(&mon,&v));++mon.version;
 MechanicalDobMonitor saved=mon;
 MechanicalDobMonitor_Lifecycle(&mon,0,0);
 assert(!mon.current.valid && mon.frozen==DOB_MONITOR_OFF && mon.current.disturbance_a==0);
 assert(!memcmp(saved.frames,mon.frames,sizeof mon.frames));
 MechanicalDobMonitor_Lifecycle(&mon,1,0); /* no automatic re-arm */
 unsigned n=mon.observations;sample(.3f,0,50);assert(mon.observations==n);
}
/* Same 20ms pole on Iq and measured speed; no raw acceleration amplifier. */
reset();float w_filtered=30;
for(unsigned i=0;i<3000;i++){
 float w=30+5.f*i*.001f;w_filtered+=.001f/(.020f+.001f)*(w-w_filtered);
 sample(current(w,.02f)+m->j_over_kt*5.f,.005f,w_filtered);
}
assert(mon.current.valid && fabsf(mon.current.disturbance_a-.02f)<2e-5f);
/* Invalid data reset only diagnostics, and must warm again before valid. */
MechanicalDobMonitor_Observe(&mon,enc+20,enc,1000,50,0,0,0);
assert(!mon.current.valid && (mon.current.status&DOB_MONITOR_CURRENT));
assert(mon.current.iq_matched_a==0 && mon.current.disturbance_a==0);
enc+=1000;seq+=20;sample(current(50,0),.005f,50);assert(!mon.current.valid);
for(unsigned i=0;i<1500;i++)sample(current(50,0),.005f,50);
assert(mon.current.valid && fabsf(mon.current.disturbance_a)<1e-5f);
MechanicalCurrent c={2,seq,enc-300,enc,.005f,.2f,0};
MechanicalDobMonitor_Observe(&mon,enc+20,enc,1000,50,0,&c,1);
assert(!mon.current.valid && (mon.current.status&DOB_MONITOR_TIME));
reset();c=(MechanicalCurrent){2,seq,enc-20,enc,.005f,.2f,MEC_SATURATED};
MechanicalDobMonitor_Observe(&mon,enc+20,enc,1000,50,0,&c,1);
assert(!mon.current.valid && (mon.current.status&DOB_MONITOR_SATURATED));
reset();sample(.2f,.005f,50);seq-=20;sample(.2f,.005f,50);
assert(!mon.current.valid && (mon.current.status&DOB_MONITOR_SEQUENCE));
reset();sample(.2f,.005f,50);enc+=1000;sample(.2f,.005f,50);
assert(!mon.current.valid && (mon.current.status&DOB_MONITOR_SEQUENCE));
reset();sample(NAN,0,50);assert(!mon.current.valid && (mon.current.status&DOB_MONITOR_CURRENT));
reset();sample(.2f,0,NAN);assert(!mon.current.valid);
reset();for(unsigned i=0;i<1000;i++)sample(.2f,.08f,50);
assert(!mon.current.valid && mon.current.status==DOB_MONITOR_ID);
for(unsigned i=0;i<1500;i++)sample(current(50,0),.005f,50);
assert(mon.current.valid);
sample(.2f,.005f,0);assert(!mon.current.valid && mon.current.status==DOB_SHADOW_ZERO_SPEED);
/* Encoder and ADC timestamps/seq may wrap through zero normally. */
reset();enc=0xfffff830U;seq=0xfffffff0U;
for(unsigned i=0;i<1500;i++)sample(current(-50,0),.005f,-50);
assert(mon.current.valid && !mon.rejected_samples);
/* Real outer epochs can read an ADC pair AFTER the encoder receive.
 * Both ages are checked against captured observed_us, not each other. */
reset();
for(unsigned i=0;i<1500;i++){
 MechanicalCurrent later={2,seq,enc+115,enc+134,.005f,current(50,.02f),0};
 MechanicalDobMonitor_Observe(&mon,enc+160,enc,1000,50,0,&later,1);
 enc+=1000;seq+=20;
}
assert(mon.current.valid && !mon.rejected_samples);
MechanicalDobMonitor_Lifecycle(&mon,1,1);
assert(!mon.current.valid && mon.current.status==DOB_SHADOW_FAULT && mon.current.disturbance_a==0);
MechanicalDobMonitor_Lifecycle(&mon,1,0);assert(!mon.running);
return 0;}
'''
        for opt in ('-Os','-O2'):
            exe=ROOT/'tmp'/('dob-monitor-host'+opt+'.exe')
            p=subprocess.run([GCC,'-std=c11',opt,'-Wall','-Wextra','-Werror',
                '-I',str(ROOT/'firmware_common'),str(ROOT/'firmware_common/mechanical_dob_monitor.c'),
                '-x','c','-','-o',str(exe)],input=code,text=True,capture_output=True)
            self.assertEqual(p.returncode,0,p.stdout+p.stderr)
            p=subprocess.run([str(exe)],text=True,capture_output=True)
            self.assertEqual(p.returncode,0,p.stdout+p.stderr)

    def test_parameters_exactly_match_verified_joint_model_not_positive_intercept(self):
        report=json.loads((ROOT/'tmp/mechanical-bidirectional-fit-1792713255600021200.json').read_text())
        self.assertTrue(report['normalized_bidirectional_qualified'])
        model=report['candidate_dob_shadow_model']
        # Check the actual original SHADOW profile, not the first textual arm
        # of a new candidate-only #if in the shared model initializer.
        build=ROOT/'foc2_app_a/build'/NEW
        command=next(c['command'] for c in json.loads((build/'compile_commands.json').read_text())
                     if c['file'].endswith('/mechanical_dob_monitor.c'))
        p=subprocess.run(re.sub(r' -o \S+ -c ',' -E -P ',command),cwd=build,text=True,capture_output=True)
        self.assertEqual(p.returncode,0,p.stderr)
        source=p.stdout
        for key,value in model.items():
            text=re.search(r'\.'+key+r'=([^,}\s]+)',source).group(1)
            self.assertAlmostEqual(float(text.rstrip('fU')),value,places=11)
        self.assertNotAlmostEqual(model['coulomb_over_kt'],.1207347545555368,places=5)

    def test_no_control_feedback_and_only_post_ack_observation_hook(self):
        old=expanded('a',OLD);new=expanded('a',NEW)
        for name in ('FOC_CurrentLoopStep','FOC_EncoderSpeedUpdate','ProtectedLoop_AdcIrq',
            'ProtectedLoop_GuardIrqBody','ProtectedLoop_HealthCaptured','FaultDiag_CapturePacked',
            'ProtectedLoop_TimerHealthy','ProtectedLoop_GatesMatch','ProtectedLoop_PwmEntry',
            'ProtectedLoop_PwmStage','ProtectedLoop_Ready','LatestOriginal_Admit',
            'LatestOriginal_Ready','PowerStage_Enable','PowerStage_Disable','MotorControl_SetIq',
            'MotorControl_SetSpeed','Encoder_ElectricalAngleRad','TighteningTask'):
            self.assertEqual(function(old,name),function(new,name),name)
        task=function(new,'ProtectedLoop_TaskService')
        start=task.index('MechanicalDobMonitor_Lifecycle');end=task.index(';',start)+1
        self.assertEqual(re.sub(r'\s+','',function(old,'ProtectedLoop_TaskService')),
            re.sub(r'\s+','',task[:start]+task[end:]))
        self.assertLess(task.index('cl_session.outer_us='),task.index('OuterObservation_Flush'))
        flush=function(new,'OuterObservation_Flush')
        start=flush.index('uint32_t dob_begin=')
        self.assertEqual(re.sub(r'\s+','',function(old,'OuterObservation_Flush')),
            re.sub(r'\s+','',flush[:start]+'}'))
        for path in ('mechanical_dob_monitor.c','mechanical_dob_monitor.h','mechanical_dob_binding.inc'):
            code=(ROOT/'firmware_common'/path).read_text()
            for token in ('foc_iq_ref_A','foc_int_','MotorControl_Set','PWM_SetDuty','DmaAcknowledge',
                '__disable_irq','taskENTER_CRITICAL','malloc','->CCR','->BDTR'):
                self.assertNotIn(token,code,path)

    def test_build_isolation_ram_objects_and_no_warning_delta(self):
        self.assertNotIn('FOC_MECHANICAL_DOB_SHADOW',(ROOT/'foc2_app_b/CMakeLists.txt').read_text())
        for p,sha in ((ROOT/'foc2_app_a/build'/OLD/'foc2.bin','abffd548ede6d1b9b635d4ce170554b728cb44f6ba9425f4db43124b00ca5706'),
            (ROOT/'foc2_app_b/build/MechanicalReviewB/foc2.bin','7ebdb56408baaa6c213c5dabe236250be673ed5a5c1345dfe64861d1e98dd366')):
            self.assertEqual(hashlib.sha256(p.read_bytes()).hexdigest(),sha)
        for name in ('stm32g4xx_it.c.obj','foc_adc_timing_stm32.c.obj','as5047p_dma_stm32.c.obj',
            'foc_zero_robust.c.obj','tightening_intent_fsm.c.obj','speed_scurve.c.obj',
            'mechanical_identification.c.obj','speed_accel_feedforward.c.obj','speed_friction_compensation.c.obj'):
            self.assertEqual(next((ROOT/'foc2_app_a/build'/OLD).rglob(name)).read_bytes(),
                next((ROOT/'foc2_app_a/build'/NEW).rglob(name)).read_bytes(),name)
        warning_sets=[]
        for preset in (OLD,NEW):
            directory=ROOT/'foc2_app_a/build'/preset
            command=next(c['command'] for c in json.loads((directory/'compile_commands.json').read_text()) if c['file'].endswith('/Core/Src/main.c'))
            p=subprocess.run(re.sub(r' -o \S+ -c ',' -fsyntax-only ',command),cwd=directory,text=True,capture_output=True)
            self.assertEqual(p.returncode,0,p.stdout+p.stderr)
            warning_sets.append(set(re.findall(r'warning: (.*)',p.stderr)))
        self.assertEqual(*warning_sets)

    def test_readonly_uart_model_live_status_cannot_toggle_feedback(self):
        binding=(ROOT/'firmware_common/mechanical_dob_binding.inc').read_text()
        code=r'''
#include <assert.h>
#include <math.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include "mechanical_dob_monitor.h"
static MechanicalDobMonitor mechanical_dob_monitor;
static unsigned cl_armed,adc_fault,foc_fault;
static struct {unsigned state;} cl_session;
#define CL_RUNNING 2U
static uint32_t AS5047P_DmaNowUs(void){return 1000;}
'''+binding+r'''
int main(void){char out[192]; /* Real Protocol_ProcessLine reply capacity. */
assert(MechanicalDob_Command("MOTOR TEST MECH DOB MODEL",out,sizeof out));
assert(strstr(out,"FEEDBACK=0") && strstr(out,"IC_UA=119451"));
assert(!MechanicalDob_Command("MOTOR TEST MECH DOB ON",out,sizeof out));
cl_armed=1;cl_session.state=CL_RUNNING;
MechanicalDobMonitor_Lifecycle(&mechanical_dob_monitor,1,0);
mechanical_dob_monitor.current=(MechanicalDobMonitorFrame){.sample_us=900,.valid=1,.status=0,
 .adc_seq=123456,.adc_source_us=890,.adc_published_us=900,.omega_rad_s=62.8f,
 .iq_a=.2f,.iq_matched_a=.2f,.id_a=.005f,.disturbance_a=.02f};
assert(MechanicalDob_Command("MOTOR TEST MECH DOB",out,sizeof out));
assert(strstr(out,"LIVE=1 VALID=1") && strstr(out,"D_UA="));
assert(MechanicalDob_Command("MOTOR TEST MECH DOB ADC",out,sizeof out));
assert(strstr(out,"LIVE=1 VALID=1") && strstr(out,"ADC_US=890 PUB_US=900"));
assert(MechanicalDob_Command("MOTOR TEST MECH DOB STATS",out,sizeof out));
assert(strlen(out)<sizeof(out)-1 && strstr(out,"MAX_US=") && strstr(out,"NEG_UA="));
adc_fault=1;MechanicalDob_Command("MOTOR TEST MECH DOB",out,sizeof out);
assert(strstr(out,"LIVE=0 VALID=0") && strstr(out,"FEEDBACK=0"));
adc_fault=0;mechanical_dob_monitor.current.sample_us=0xffff0000U;
MechanicalDob_Command("MOTOR TEST MECH DOB",out,sizeof out);assert(strstr(out,"LIVE=0 VALID=0"));
mechanical_dob_monitor.version|=1;
MechanicalDob_Command("MOTOR TEST MECH DOB",out,sizeof out);assert(strstr(out,"BUSY=1"));
assert(MechanicalDob_Fixed(NAN,1e6f)==0 && MechanicalDob_Fixed(INFINITY,1e6f)==0);
/* Every readonly reply must fit even at uint32/int32 field extremes. */
mechanical_dob_monitor.version++;
mechanical_dob_monitor.observations=mechanical_dob_monitor.valid_samples=0xffffffffU;
mechanical_dob_monitor.rejected_samples=mechanical_dob_monitor.max_compute_us=0xffffffffU;
mechanical_dob_monitor.positive_n=mechanical_dob_monitor.negative_n=1;
mechanical_dob_monitor.positive_sum=mechanical_dob_monitor.negative_sum=-1e20f;
mechanical_dob_monitor.disturbance_abs_peak=1e20f;
mechanical_dob_monitor.current=(MechanicalDobMonitorFrame){.status=2047,.sample_us=0xffffffffU,
 .adc_seq=0xffffffffU,.adc_source_us=0xffffffffU,.adc_published_us=0xffffffffU,
 .omega_rad_s=-1e20f,.iq_a=-1e20f,.iq_matched_a=-1e20f,.id_a=-1e20f,.disturbance_a=-1e20f};
const char *commands[]={"MOTOR TEST MECH DOB","MOTOR TEST MECH DOB ADC",
 "MOTOR TEST MECH DOB STATS","MOTOR TEST MECH DOB MODEL"};
const char *last[]={"D_UA=-2147483000","PUB_US=4294967295","NEG_UA=-2147483000","MIN_W_MRAD_S=2094"};
for(unsigned i=0;i<4;i++){
 assert(MechanicalDob_Command(commands[i],out,sizeof out));
 assert(strlen(out)<sizeof(out)-1 && strstr(out,last[i]));
}
return 0;}
'''
        exe=ROOT/'tmp/dob-monitor-protocol-host.exe'
        p=subprocess.run([GCC,'-std=c11','-Os','-Wall','-Wextra','-Werror','-I',str(ROOT/'firmware_common'),
            str(ROOT/'firmware_common/mechanical_dob_monitor.c'),'-x','c','-','-o',str(exe)],input=code,text=True,capture_output=True)
        self.assertEqual(p.returncode,0,p.stdout+p.stderr)
        p=subprocess.run([str(exe)],text=True,capture_output=True)
        self.assertEqual(p.returncode,0,p.stdout+p.stderr)


if __name__=='__main__':unittest.main()
