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


class IdSteadyTests(unittest.TestCase):
    def test_native_unbiased_moments_fixed_window_over_duration_gaps_saturation_stop_and_wrap(self):
        code=r'''
#include <assert.h>
#include <math.h>
#include <stddef.h>
#include <string.h>
#include "id_steady_stats.h"
#include "mechanical_dob_monitor.h"
static IdSteadyStats s;
static uint32_t enc,seq;
static void sample(float id,float ref,float filtered,float rpm,float accel,unsigned valid,unsigned flags,unsigned dob){
 MechanicalCurrent c={2,seq,enc+115,enc+134,id,.22f,flags};
 IdSteady_Observe(&s,enc+160,enc,1000,600,accel,rpm,ref,0,&c,valid,filtered,dob,0);
 enc+=1000;seq+=20;
}
static void reset(uint32_t t){memset(&s,0,sizeof s);enc=t;seq=20;IdSteady_Lifecycle(&s,1,0);}
static void qualify(void){for(unsigned i=0;i<499;i++)sample(.01f,0,.01f,600,0,1,0,DOB_SHADOW_WARMUP);assert(s.state==IDS_WAIT);}
int main(void){
 assert(sizeof s==336 && offsetof(IdSteadyStats,signal)==84);
 assert(offsetof(IdSteadyStats,raw_over)==184 && offsetof(IdSteadyStats,dob_status_n)==284);
 for(unsigned wrap=0;wrap<2;wrap++){
 reset(wrap?0xffff0000U:1000U);qualify();
 for(unsigned i=0;i<1000;i++)sample(i<100?.1f:.01f,0,i<50?.06f:.02f,600,0,1,0,DOB_MONITOR_ID);
 assert(s.state==IDS_DONE && s.good_n==1000 && s.good_us==1000000 && !s.bad_us);
 assert(fabsf(s.signal[IDS_ID].integral/1e6f-.019f)<1e-6f);
 assert(fabsf(s.signal[IDS_ID].sq_integral/1e6f-.00109f)<1e-7f);
 assert(s.signal[IDS_ID].min==.01f && s.signal[IDS_ID].max==.1f);
 assert(s.signal[IDS_IDREF].integral==0 && fabsf(s.signal[IDS_IQ].integral/1e6f-.22f)<1e-5f);
 assert(s.raw_over.total_us==100000 && s.raw_over.max_us==100000 && s.raw_over.episodes==1);
 assert(s.raw_over.bins[3]==1 && !s.raw_over.censored);
 assert(s.filtered_over.total_us==50000 && s.filtered_over.max_us==50000 && s.filtered_over.bins[2]==1);
 assert(s.abs_id_bins[0]==900 && s.abs_id_bins[2]==100);
 assert(s.positive_over_us==100000 && !s.negative_over_us);
 assert(s.dob_status_n[9]==1000); /* DOB ID rejection does NOT censor these data. */
 IdSteadyStats saved=s;sample(9,0,9,600,0,1,0,0);
 assert(!memcmp(s.signal,saved.signal,sizeof s.signal));
 IdSteadyView v;assert(IdSteady_Read(&s,&v) && v.good_n==1000);
 s.version|=1;assert(!IdSteady_Read(&s,&v));++s.version;
 IdSteady_Lifecycle(&s,0,0);assert(s.frozen && !s.running && s.state==IDS_DONE);
 unsigned n=s.good_n;IdSteady_Lifecycle(&s,1,0);sample(9,0,9,600,0,1,0,0);assert(s.good_n==n);
 }
 reset(1000);qualify();
 for(unsigned i=0;i<1000;i++)sample(i%10==0?-.2f:0,.02f,.01f,600,0,1,0,0);
 assert(s.raw_over.total_us==100000 && s.raw_over.max_us==1000 && s.raw_over.episodes==100);
 assert(s.raw_over.bins[0]==100 && s.negative_over_us==100000);
 assert(fabsf(s.signal[IDS_IDREF].integral/1e6f-.02f)<1e-6f);
 assert(fabsf(s.signal[IDS_IDERROR].integral/1e6f+.04f)<1e-6f);
 reset(1000);qualify();
 for(unsigned i=0;i<1000;i++)sample(.1f,0,.06f,600,0,i!=500,0,0);
 assert(s.good_us==999000 && s.bad_us==1000 && s.bad_n==1);
 assert(s.filtered_good_us==999000 && s.filtered_bad_us==1000);
 assert(s.raw_over.episodes==2 && s.raw_over.max_us==500000 && s.raw_over.censored==2);
 reset(1000);qualify();
 for(unsigned i=0;i<1000;i++)sample(.1f,0,.06f,600,0,1,i<50?MEC_SATURATED:0,i<50?DOB_MONITOR_SATURATED:0);
 assert(s.good_us==1000000 && s.voltage_sat_us==50000 && !s.bad_us);
 assert(s.filtered_bad_us==50000 && s.filtered_over.total_us==950000);
 reset(1000);
 for(unsigned i=0;i<600;i++)sample(.1f,0,.06f,550,0,1,0,0);
 assert(s.state==IDS_WAIT && s.stable_us==0);
 for(unsigned i=0;i<600;i++)sample(.1f,0,.06f,600,2,1,0,0);
 assert(s.state==IDS_WAIT);qualify();
 for(unsigned i=0;i<1000;i++)sample(.1f,0,.06f,i<10?600:550,0,1,0,0);
 assert(s.state==IDS_DONE && s.unstable_us==990000); /* No cherry-picked restart. */
 reset(1000);qualify();sample(NAN,0,.01f,600,0,1,0,0);
 assert(s.bad_n==1 && !s.good_n && isfinite(s.signal[IDS_ID].integral));
 IdSteady_Lifecycle(&s,1,1);assert(s.state==IDS_INCOMPLETE && s.frozen);
 return 0;}
'''
        for opt in ('-Os','-O2'):
            exe=ROOT/'tmp'/('id-steady-host'+opt+'.exe')
            p=subprocess.run([GCC,'-std=c11',opt,'-Wall','-Wextra','-Werror','-I',str(ROOT/'firmware_common'),
                str(ROOT/'firmware_common/id_steady_stats.c'),'-x','c','-','-o',str(exe)],input=code,text=True,capture_output=True)
            self.assertEqual(p.returncode,0,p.stdout+p.stderr)
            p=subprocess.run([str(exe)],text=True,capture_output=True)
            self.assertEqual(p.returncode,0,p.stdout+p.stderr)

    def test_control_irq_protection_and_dob_gate_unchanged_post_ack_only(self):
        old=expanded('a','MechanicalDobShadowCandidate');new=expanded('a','MechanicalIdSteadyCandidate')
        for name in ('FOC_CurrentLoopStep','FOC_EncoderSpeedUpdate','ProtectedLoop_AdcIrq',
            'ProtectedLoop_GuardIrqBody','ProtectedLoop_Ready','LatestOriginal_Admit',
            'PowerStage_Enable','PowerStage_Disable','MotorControl_SetIq','MotorControl_SetSpeed',
            'Encoder_ElectricalAngleRad','TighteningTask'):
            self.assertEqual(function(old,name),function(new,name),name)
        task=function(new,'ProtectedLoop_TaskService');start=task.index('IdSteady_Lifecycle');end=task.index(';',start)+1
        self.assertEqual(re.sub(r'\s+','',function(old,'ProtectedLoop_TaskService')),
                         re.sub(r'\s+','',task[:start]+task[end:]))
        flush=function(new,'OuterObservation_Flush');start=flush.index('uint32_t ids_begin=')
        self.assertEqual(re.sub(r'\s+','',function(old,'OuterObservation_Flush')),
                         re.sub(r'\s+','',flush[:start]+'}'))
        for name in ('stm32g4xx_it.c.obj','foc_adc_timing_stm32.c.obj','as5047p_dma_stm32.c.obj',
                     'foc_zero_robust.c.obj','mechanical_dob_monitor.c.obj','speed_scurve.c.obj'):
            self.assertEqual(next((ROOT/'foc2_app_a/build/MechanicalDobShadowCandidate').rglob(name)).read_bytes(),
                             next((ROOT/'foc2_app_a/build/MechanicalIdSteadyCandidate').rglob(name)).read_bytes(),name)
        self.assertEqual(hashlib.sha256((ROOT/'foc2_app_a/build/MechanicalDobShadowCandidate/foc2.bin').read_bytes()).hexdigest(),
                         '74d53cf4e47743ccfa8bfbe5ca73ed4d58dcc0332ca59b785bfe8b54bb84e770')
        self.assertNotIn('FOC_ID_STEADY_STATS',(ROOT/'foc2_app_b/CMakeLists.txt').read_text())

    def test_no_warning_delta(self):
        warnings=[]
        for preset in ('MechanicalDobShadowCandidate','MechanicalIdSteadyCandidate'):
            directory=ROOT/'foc2_app_a/build'/preset
            command=next(c['command'] for c in json.loads((directory/'compile_commands.json').read_text()) if c['file'].endswith('/Core/Src/main.c'))
            p=subprocess.run(re.sub(r' -o \S+ -c ',' -fsyntax-only ',command),cwd=directory,text=True,capture_output=True)
            self.assertEqual(p.returncode,0,p.stdout+p.stderr)
            warnings.append(set(re.findall(r'warning: (.*)',p.stderr)))
        self.assertEqual(*warnings)

    def test_readonly_protocol_real_192_byte_capacity_no_enable(self):
        binding=(ROOT/'firmware_common/id_steady_binding.inc').read_text()
        code=r'''
#include <assert.h>
#include <stdio.h>
#include <string.h>
#include "id_steady_stats.h"
static IdSteadyStats id_steady_stats;
'''+binding+r'''
int main(void){char out[192];
assert(IdSteady_Command("MOTOR TEST MECH IDSTATS CFG",out,sizeof out));
assert(strstr(out,"THRESH_UA=50000") && strstr(out,"FEEDBACK=0"));
assert(!IdSteady_Command("MOTOR TEST MECH IDSTATS ON",out,sizeof out));
id_steady_stats.state=id_steady_stats.good_n=id_steady_stats.good_us=id_steady_stats.bad_us=0xffffffffU;
id_steady_stats.raw_over.total_us=id_steady_stats.filtered_over.total_us=id_steady_stats.max_compute_us=0xffffffffU;
assert(IdSteady_Command("MOTOR TEST MECH IDSTATS",out,sizeof out));
assert(strlen(out)<191 && strstr(out,"MAX_US=4294967295 FEEDBACK=0"));
id_steady_stats.version=1;
assert(IdSteady_Command("MOTOR TEST MECH IDSTATS",out,sizeof out) && strstr(out,"BUSY=1"));
return 0;}
'''
        exe=ROOT/'tmp/id-steady-protocol-host.exe'
        p=subprocess.run([GCC,'-std=c11','-Os','-Wall','-Wextra','-Werror','-I',str(ROOT/'firmware_common'),
            str(ROOT/'firmware_common/id_steady_stats.c'),'-x','c','-','-o',str(exe)],input=code,text=True,capture_output=True)
        self.assertEqual(p.returncode,0,p.stdout+p.stderr)
        p=subprocess.run([str(exe)],text=True,capture_output=True)
        self.assertEqual(p.returncode,0,p.stdout+p.stderr)


if __name__=='__main__':unittest.main()
