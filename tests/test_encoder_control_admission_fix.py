"""Actual saved 600rpm fault plus compiled A-only encoder admission regression.

No serial/SWD or motor operation. Prior hardware image/ELF/RAM remain immutable.
"""
import hashlib
import json
from pathlib import Path
import re
import struct
import subprocess
import sys
import unittest
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
from foc_path_profile_report import symbols
import current_pi_compare as compiler
from test_torque_chain import function
from test_torque350_five_second import expanded

OLD='MechanicalIdentificationHighSpeedCandidate'
NEW='MechanicalHighSpeedEncoderFixCandidate'
RECEIPT=ROOT/'tmp/mechanical-ident-run-1792671182051071100.json'


class EncoderControlAdmissionTests(unittest.TestCase):
    def test_saved_fault_proves_unraised_legacy_ceiling_not_spi_timeout(self):
        r=json.loads(RECEIPT.read_text());ram=Path(r['ram_capture']).read_bytes()
        elf=ROOT/'foc2_app_a/build'/OLD/'foc2.elf'
        self.assertEqual(hashlib.sha256(ram).hexdigest(),r['ram_sha256'])
        self.assertEqual(hashlib.sha256(elf.read_bytes()).hexdigest(),r['elf_sha256'])
        sym=symbols(elf)
        def value(key,fmt):
            addr,size=sym[key];self.assertEqual(size,struct.calcsize(fmt))
            return struct.unpack_from(fmt,ram,addr-0x20000000)[0]
        self.assertEqual(value('encoder_speed_glitch_streak','<I'),2)
        self.assertEqual(value('encoder_speed_glitch_count','<I'),8)
        self.assertEqual(value('encoder_prev_raw','<H'),2508)
        self.assertAlmostEqual(value('encoder_speed_dt_accum_s','<f'),.002,places=8)
        self.assertAlmostEqual(value('encoder_rpm_instant','<f'),615.234375)
        sample=next(s for s in r['encoder_saved']['publication_banks'] if s['status']==0)
        self.assertEqual(sample['raw'],2172)
        actual_rpm=-(sample['raw']-2508)*60/(16384*.002)
        self.assertAlmostEqual(actual_rpm,615.234375)
        self.assertGreater(actual_rpm,600);self.assertLess(actual_rpm,1000)
        self.assertEqual(r['encoder_saved']['counters']['control_stale'],1)
        self.assertEqual(r['encoder_saved']['counters']['timeouts'],0)
        self.assertEqual(r['encoder_saved']['counters']['dma_errors'],0)
        due=value('control_due_us','<I')
        self.assertEqual(r['encoder_saved']['first_fault']['now_us']-due,1)
        self.assertEqual(r['snapshot']['first_fault']['protection_flags'],32)

    def test_actual_reject_branch_and_outer_heartbeat_boundaries(self):
        # Compile the actual preprocessed rejection branch and actual outer
        # service prefix. Only HAL/IO/clock and accepted publication are stubs.
        for preset,fixed in ((OLD,False),(NEW,True)):
            source=expanded('a',preset)
            full=function(source,'FOC_EncoderSpeedUpdate')
            begin=full.index('if (fabsf(rpm_inst) >')
            end=full.index('encoder_speed_glitch_streak = 0U;',begin)
            rejection=full[begin:end]
            task=function(source,'ProtectedLoop_TaskService')
            task='static void '+task[:task.index('if (update==HAL_BUSY) return;')+len('if (update==HAL_BUSY) return;')]+'\n}'
            preamble=r'''
#include <assert.h>
#include <stdint.h>
#include <math.h>
typedef enum { HAL_OK=0,HAL_ERROR=1,HAL_BUSY=2 } HAL_StatusTypeDef;
static unsigned encoder_speed_glitch_count,encoder_speed_glitch_streak;
static unsigned foc_fault_reason,foc_fault,encoder_valid,adc_fault,cl_armed;
static unsigned gates_off,cl_outer_n,acks,periodic=1;
static uint32_t clock_us,control_due_us;
static struct {uint32_t outer_us;} cl_session;
static float input_rpm,angle,foc_iq_ref_A;
static unsigned force_busy,force_error;
#define SPEED_GLITCH_STREAK_LIMIT 3U
#define CL_BAD_ENCODER 32U
static void PowerStage_Disable(void){gates_off=1;}
static void FaultDiag_Motor(unsigned x){(void)x;}
static void MotorControl_SetIdle(void){}
static int AS5047P_DmaIsPeriodic(void){return periodic;}
static void AS5047P_DmaStopPeriodic(void){periodic=0;}
static int AS5047P_DmaStartPeriodic(void){periodic=1;return 1;}
static uint32_t AS5047P_DmaNowUs(void){return clock_us;}
static void ProtectedLoop_EmergencyOff(unsigned x){(void)x;gates_off=1;cl_armed=0;}
static void reset(void){
 encoder_speed_glitch_count=encoder_speed_glitch_streak=0;
 foc_fault_reason=foc_fault=adc_fault=gates_off=0;encoder_valid=cl_armed=periodic=1;
 clock_us=1000;control_due_us=3500;cl_session.outer_us=1000;
 cl_outer_n=acks=force_busy=force_error=0;angle=0;
}
static HAL_StatusTypeDef FOC_EncoderSpeedUpdate(float dt){
 (void)dt;if(force_busy)return HAL_BUSY;if(force_error)return HAL_ERROR;
 float rpm_inst=input_rpm;
''' + rejection + r'''
 encoder_speed_glitch_streak=0;
 if ((int32_t)(clock_us-control_due_us)>=0) {gates_off=1;foc_fault=1;return HAL_ERROR;}
 angle+=rpm_inst*.006f;++acks;control_due_us=clock_us+2500;
 return HAL_OK;
}
''' + task + r'''
int main(void){
 reset();input_rpm=615.234375f;clock_us=2000;ProtectedLoop_TaskService();
 if(FIXED){assert(acks==1 && cl_outer_n==1 && angle>0 && control_due_us==4500);}
 else {assert(!acks && cl_outer_n==1 && angle==0 && control_due_us==3500);}
 /* Normal high-speed samples cannot silently fail at 600 in the new A. */
 if(FIXED){
  float speeds[]={600,615.234375f,700,800,999.9f,-615.234375f,-800};
  for(unsigned i=0;i<sizeof speeds/sizeof speeds[0];i++){
   reset();input_rpm=speeds[i];clock_us=2000;ProtectedLoop_TaskService();
   assert(acks==1 && cl_outer_n==1 && !gates_off);
  }
 }
 /* Truly impossible jumps NEVER ACK or extend control watchdog. */
 reset();input_rpm=1200;clock_us=2000;ProtectedLoop_TaskService();
 assert(!acks && !angle && control_due_us==3500 && encoder_speed_glitch_streak==1);
 assert(cl_outer_n==(FIXED?0u:1u));
 if(FIXED)assert(cl_session.outer_us==1000);
 clock_us=3000;ProtectedLoop_TaskService();assert(!acks && !gates_off);
 assert(encoder_speed_glitch_streak==2 && control_due_us==3500);
 clock_us=3500;
 assert((int32_t)(clock_us-control_due_us)>=0); /* original watchdog still due */
 reset();input_rpm=1200;
 for(unsigned i=0;i<3;i++){clock_us=1100+i*100;ProtectedLoop_TaskService();}
 assert(gates_off && foc_fault && !encoder_valid && !acks && foc_fault_reason==2);
 /* Recovery after one rejected point is allowed only on a fresh accepted one. */
 reset();input_rpm=1200;clock_us=2000;ProtectedLoop_TaskService();
 input_rpm=500;clock_us=3000;ProtectedLoop_TaskService();
 assert(acks==1 && !gates_off && encoder_speed_glitch_streak==0);
 /* Duplicate/no sample and failed sample cannot count as success. */
 reset();force_busy=1;clock_us=2000;ProtectedLoop_TaskService();
 assert(!acks && !cl_outer_n && cl_session.outer_us==1000);
 reset();force_error=1;ProtectedLoop_TaskService();assert(gates_off && !acks);
 /* A genuinely late accepted computation may not backdate/refresh deadline. */
 reset();input_rpm=500;clock_us=3500;ProtectedLoop_TaskService();
 assert(gates_off && !acks && control_due_us==3500);
 return 0;
}
'''
            # Guard reset call appears in the actual branch; provide its type.
            if 'SpeedBrakeTrack_Reset' in rejection:
                preamble='static int speed_brake_track;static void SpeedBrakeTrack_Reset(int *s){(void)s;}\n'+preamble
            preamble='#define FIXED '+str(int(fixed))+'\n'+preamble
            for opt in ('-Os','-O2'):
                exe=ROOT/'tmp'/('encoder-control-admission-'+str(fixed)+opt+'.exe')
                p=subprocess.run([str(compiler.GCC),'-std=c11',opt,'-Wall','-Wextra','-Werror',
                    '-x','c','-','-o',str(exe)],input=preamble,text=True,capture_output=True)
                self.assertEqual(p.returncode,0,p.stdout+p.stderr)
                p=subprocess.run([str(exe)],text=True,capture_output=True)
                self.assertEqual(p.returncode,0,p.stdout+p.stderr)

    def test_config_scoped_and_no_control_math_or_irq_or_watchdog_changes(self):
        old=expanded('a',OLD);new=expanded('a',NEW)
        for name in ('FOC_CurrentLoopStep','ProtectedLoop_TaskService','ProtectedLoop_HealthCaptured',
            'ProtectedLoop_PwmEntry','ProtectedLoop_PwmStage','ProtectedLoop_GuardIrqBody',
            'PowerStage_Enable','PowerStage_Disable','Encoder_ElectricalAngleRad','LatestOriginal_Admit',
            'MotorControl_SetIq','MotorControl_SetSpeed','TighteningTask'):
            self.assertEqual(function(old,name),function(new,name),name)
        a=function(old,'FOC_EncoderSpeedUpdate');b=function(new,'FOC_EncoderSpeedUpdate')
        before='if (fabsf(rpm_inst) > 600.0f)'
        after='if (fabsf(rpm_inst) > ((float)1000U))'
        self.assertIn(before,a);self.assertIn(after,b)
        b=b.replace(after,before)
        start=b.index(before);end=b.index('encoder_speed_glitch_streak = 0U;',start)
        region=b[start:end];self.assertEqual(region.count('return HAL_BUSY;'),1)
        b=b[:start]+region.replace('return HAL_BUSY;','return HAL_OK;')+b[end:]
        norm=lambda s:re.sub(r'\s+','',s)
        self.assertEqual(norm(a),norm(b))
        for name in ('TRANSACTION','SCHEDULE_LATE','PERIOD','SAMPLE_MAX_AGE','CONTROL_WATCHDOG'):
            expected=dict(TRANSACTION=200,SCHEDULE_LATE=200,PERIOD=1000,SAMPLE_MAX_AGE=1500,CONTROL_WATCHDOG=2500)
            self.assertRegex((ROOT/'firmware_common/as5047p_timing_policy.h').read_text(),rf'AS_DMA_{name}_US\s+{expected[name]}U')
        for file in ('as5047p_dma_stm32.c.obj','stm32g4xx_it.c.obj','foc_adc_timing_stm32.c.obj',
            'foc_zero_robust.c.obj','tightening_intent_fsm.c.obj','mechanical_identification.c.obj'):
            self.assertEqual(next((ROOT/'foc2_app_a/build'/OLD).rglob(file)).read_bytes(),
                             next((ROOT/'foc2_app_a/build'/NEW).rglob(file)).read_bytes(),file)
        self.assertNotIn('FOC_ENCODER_CONTROL_ADMISSION_FIX',(ROOT/'foc2_app_b/CMakeLists.txt').read_text())
        self.assertEqual(hashlib.sha256((ROOT/'foc2_app_a/build'/OLD/'foc2.bin').read_bytes()).hexdigest(),
            '442cef6ca8476b15e99e373b01394f881672e89fb5a2ff5a176323e0e3fcec1e')

    def test_no_new_warning_set_and_b_preserved(self):
        warning_sets=[]
        for preset in (OLD,NEW):
            directory=ROOT/'foc2_app_a/build'/preset
            cmd=next(c['command'] for c in json.loads((directory/'compile_commands.json').read_text()) if c['file'].endswith('/Core/Src/main.c'))
            p=subprocess.run(re.sub(r' -o \S+ -c ',' -fsyntax-only ',cmd),cwd=directory,capture_output=True,text=True)
            self.assertEqual(p.returncode,0,p.stdout+p.stderr)
            warning_sets.append(set(re.findall(r'warning: (.*)',p.stderr)))
        self.assertEqual(*warning_sets)
        self.assertEqual(hashlib.sha256((ROOT/'foc2_app_b/build/FrictionBUnchanged/foc2.bin').read_bytes()).hexdigest(),
            '7ebdb56408baaa6c213c5dabe236250be673ed5a5c1345dfe64861d1e98dd366')


if __name__=='__main__':unittest.main()
