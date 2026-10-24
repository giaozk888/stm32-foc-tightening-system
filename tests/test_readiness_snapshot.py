"""Offline only: optimized actual admission functions, no serial/SWD calls."""
import hashlib
import json
from pathlib import Path
import re
import subprocess
import unittest
from test_torque_chain import GCC, function
from test_torque350_five_second import expanded

ROOT=Path(__file__).resolve().parents[1]
OLD='MechanicalOuterCompletionCandidate'
NEW='MechanicalReadinessSnapshotCandidate'


class ReadinessSnapshotTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.old=expanded('a',OLD)
        cls.new=expanded('a',NEW)

    def test_actual_optimized_admission_race_boundaries_all_predicates_and_latch(self):
        command=function(self.new,'FrictionCalibration_Command')
        # Only replace memory-mapped register addresses with host registers.
        command,n=re.subn(r'\(\(GPIO_TypeDef \*\).*?\)->ODR','(&gpio)->ODR',command)
        self.assertEqual(n,1)
        command,n=re.subn(r'\(\(TIM_TypeDef \*\).*?\)->(BDTR|CCER)',r'(&tim)->\1',command)
        self.assertEqual(n,2)
        code=r'''
#include <assert.h>
#include <stdio.h>
#include <stdint.h>
#include <string.h>
#include <math.h>
#define FOC_MECHANICAL_HIGH_SPEED_DIAG 1
#define FOC_MECHANICAL_MOTION_DIAG 1
#include "friction_calibration.h"
#include "protected_readiness.h"
#define CL_READY 1
#define FOC_OC_CLEAR 0
#define MOTOR_MODE_IDLE 0
#define CL_OVERSPEED_RPM 1000U
#define CL_MAX_US 12000000U
static struct {unsigned state,used;} cl_session;
static struct {unsigned active;} fw_update;
static struct {struct {unsigned result;} protection;} cl_safety;
static unsigned cl_armed,cl_request,adc_fault,foc_fault,run_zero_cal_done,cl_boot_confirmed;
static unsigned cl_work_n,cl_outer_n,encoder_valid,motor_control_mode,tightening_start_request;
static unsigned tightening_stop_request,speed_friction_enabled,busy,precheck;
static unsigned uart_ready,pwm_ready,periodic,timer_ok,gates_ok;
static float encoder_speed_rpm;
static uint32_t cl_last_us,clock_us,isr_timestamp,barrier_seen;
static ProtectedReadiness cl_ready_check;
static ProtectedReadinessReject cl_ready_reject;
static uint32_t cl_ready_attempts;
static FrictionCalibration friction_calibration;
static struct {uint32_t ODR;} gpio;
static struct {uint32_t BDTR,CCER;} tim;
#define DRIVER_SD_GPIO_Port (&gpio)
#define DRIVER_SD_Pin 0x40U
#define TIM1 (&tim)
#define TIM_BDTR_MOE (1U<<15)
#define TIM_BDTR_AOE (1U<<14)
#define taskENTER_CRITICAL() ((void)0)
#define taskEXIT_CRITICAL() ((void)0)
static void vPortEnterCritical(void){}
static void vPortExitCritical(void){}
static unsigned UART_Async_IsReady(void){return uart_ready;}
static unsigned ProtectedLoop_PwmNeutralReady(void){return pwm_ready;}
static unsigned AS5047P_DmaIsPeriodic(void){return periodic;}
static unsigned ProtectedLoop_TimerHealthy(void){return timer_ok;}
static unsigned ProtectedLoop_GatesMatch(void){return gates_ok;}
static unsigned Tightening_IsBusy(void){return busy;}
static unsigned TighteningIntent_PrecheckOnly(void){return precheck;}
static void __DMB(void){barrier_seen=1;}
static uint32_t AS5047P_DmaNowUs(void){
 /* Model an ADC preemption after TIM2 was read but before function return. */
 uint32_t result=clock_us;
 if(isr_timestamp)cl_last_us=isr_timestamp;
 return result;
}
'''+'static uint8_t '+function(self.new,'ProtectedLoop_AdcReady')+'\n'+\
            'static uint8_t '+function(self.new,'ProtectedLoop_Ready')+'\n'+\
            'static uint8_t '+command+r'''
static void reset(void){
 cl_session.state=CL_READY;cl_session.used=0;fw_update.active=0;cl_safety.protection.result=0;
 cl_armed=run_zero_cal_done=cl_boot_confirmed=cl_work_n=cl_outer_n=encoder_valid=1;
 uart_ready=pwm_ready=periodic=timer_ok=gates_ok=speed_friction_enabled=1;
 cl_request=adc_fault=foc_fault=motor_control_mode=tightening_start_request=tightening_stop_request=0;
 busy=precheck=0;encoder_speed_rpm=0;gpio.ODR=tim.BDTR=tim.CCER=0;
 cl_last_us=995;clock_us=1000;isr_timestamp=barrier_seen=0;
 friction_calibration=(FrictionCalibration){0};cl_ready_check=(ProtectedReadiness){0};
}
static void fail(uint32_t reason){
 assert(!ProtectedLoop_Ready());assert(cl_ready_check.failed==reason);
}
static void command_fail(uint32_t reason){
 char out[256];unsigned attempt=cl_ready_attempts+1;
 assert(FrictionCalibration_Command("MOTOR TEST MECH RUN POS 600",out,sizeof out));
 assert(!strcmp(out,"ERR MECH NOT_READY"));
 assert(cl_ready_reject.valid && cl_ready_reject.check.failed==reason);
 assert(cl_ready_reject.attempt==attempt && cl_ready_reject.rpm==600);
 assert(!friction_calibration.used && !friction_calibration.queued);
 assert(!gpio.ODR && !tim.BDTR && !tim.CCER);
}
int main(void){
 /* Demonstrate the old expression really rejects a fresh, later ISR sample. */
 reset();isr_timestamp=1005;
 uint32_t old_age=(uint32_t)(AS5047P_DmaNowUs()-cl_last_us);
 assert(old_age==4294967291U && old_age>100);
 reset();isr_timestamp=1005;
 assert(ProtectedLoop_Ready() && barrier_seen && cl_last_us==1005);
 assert(cl_ready_check.adc_us==995 && cl_ready_check.now_us==1000 && cl_ready_check.age_us==5);
 /* Original <=100 us boundary, real stale sample, zero age and timer wrap. */
 reset();cl_last_us=900;assert(ProtectedLoop_Ready() && cl_ready_check.age_us==100);
 reset();cl_last_us=899;fail(CL_READY_ADC_AGE);assert(cl_ready_check.age_us==101);
 reset();cl_last_us=1000;assert(ProtectedLoop_Ready());
 reset();cl_last_us=0xfffffff0U;clock_us=0x10;assert(ProtectedLoop_Ready() && cl_ready_check.age_us==32);
 /* New ADC arrival cannot hide a genuinely stale captured reference. */
 reset();cl_last_us=899;isr_timestamp=1005;fail(CL_READY_ADC_AGE);
 reset();cl_session.state=0;fail(CL_READY_STATE);assert(!cl_ready_check.clock_valid);
 reset();cl_session.used=1;fail(CL_READY_USED);
 reset();cl_armed=0;fail(CL_READY_ARMED);
 reset();cl_request=1;fail(CL_READY_REQUEST);
 reset();adc_fault=1;fail(CL_READY_ADC_FAULT);
 reset();foc_fault=1;fail(CL_READY_FOC_FAULT);
 reset();run_zero_cal_done=0;fail(CL_READY_ZERO);
 reset();fw_update.active=1;fail(CL_READY_UPDATE);
 reset();cl_boot_confirmed=0;fail(CL_READY_BOOT);
 reset();uart_ready=0;fail(CL_READY_UART);
 reset();pwm_ready=0;fail(CL_READY_PWM);
 reset();cl_work_n=0;fail(CL_READY_WORK);
 reset();cl_outer_n=0;fail(CL_READY_OUTER);
 reset();periodic=0;fail(CL_READY_PERIODIC);
 reset();cl_safety.protection.result=1;fail(CL_READY_CURRENT);
 reset();timer_ok=0;fail(CL_READY_TIMER);
 reset();gates_ok=0;fail(CL_READY_GATES);
 reset();encoder_valid=0;fail(CL_READY_ENCODER);
 reset();encoder_speed_rpm=2.01f;fail(CL_READY_SPEED);
 reset();encoder_speed_rpm=-2.01f;fail(CL_READY_SPEED);
 reset();encoder_speed_rpm=NAN;fail(CL_READY_SPEED);
 reset();encoder_speed_rpm=INFINITY;fail(CL_READY_SPEED);
 reset();encoder_speed_rpm=-2;assert(ProtectedLoop_Ready());
 reset();motor_control_mode=1;fail(CL_READY_MODE);
 reset();busy=1;fail(CL_READY_BUSY);
 reset();busy=precheck=1;assert(ProtectedLoop_Ready());
 reset();tightening_start_request=1;fail(CL_READY_START);
 /* MECH gates are recorded too, without changing admission or error protocol. */
 reset();friction_calibration.used=1;
 char out[256];assert(FrictionCalibration_Command("MOTOR TEST MECH RUN POS 600",out,sizeof out));
 assert(cl_ready_reject.check.failed==CL_READY_FCAL_USED && !cl_ready_reject.check.clock_valid);
 reset();cl_session.used=1;command_fail(CL_READY_USED);
 reset();cl_session.state=0;command_fail(CL_READY_STATE);
 reset();speed_friction_enabled=0;command_fail(CL_READY_FRICTION);
 reset();busy=precheck=1;command_fail(CL_READY_BUSY); /* outer gate forbids PRECHECK */
 reset();tightening_stop_request=1;command_fail(CL_READY_STOP);
 reset();gpio.ODR=DRIVER_SD_Pin;
 assert(FrictionCalibration_Command("MOTOR TEST MECH RUN POS 600",out,sizeof out));
 assert(cl_ready_reject.check.failed==CL_READY_SD && !friction_calibration.queued);
 reset();tim.BDTR=TIM_BDTR_MOE;
 assert(FrictionCalibration_Command("MOTOR TEST MECH RUN POS 600",out,sizeof out));
 assert(cl_ready_reject.check.failed==CL_READY_MOE && !friction_calibration.queued);
 reset();tim.CCER=0x555U;
 assert(FrictionCalibration_Command("MOTOR TEST MECH RUN POS 600",out,sizeof out));
 assert(cl_ready_reject.check.failed==CL_READY_CCER && !friction_calibration.queued);
 reset();cl_last_us=899;command_fail(CL_READY_ADC_AGE);
 assert(cl_ready_reject.check.now_us==1000 && cl_ready_reject.check.adc_us==899);
 ProtectedReadinessReject saved=cl_ready_reject;
 reset();assert(ProtectedLoop_Ready());
 assert(!memcmp(&saved,&cl_ready_reject,sizeof saved));
 assert(FrictionCalibration_Command("MOTOR TEST MECH READY",out,sizeof out));
 assert(strstr(out,"FIX=1 VALID=1 FAIL=0x00020000 CLOCK=1 ADC=899 NOW=1000 AGE=101 RPM=600"));
 assert(!memcmp(&saved,&cl_ready_reject,sizeof saved));
 reset();isr_timestamp=1005;
 assert(FrictionCalibration_Command("MOTOR TEST MECH RUN POS 600",out,sizeof out));
 assert(!strcmp(out,"OK MECH QUEUED RPM=600") && friction_calibration.queued);
 assert(!memcmp(&saved,&cl_ready_reject,sizeof saved));
 assert(!gpio.ODR && !tim.BDTR && !tim.CCER); /* queuing never enables PWM */
 return 0;
}
'''
        for opt in ('-Os','-O2'):
            exe=ROOT/'tmp'/('readiness-snapshot'+opt+'.exe')
            p=subprocess.run([GCC,'-std=c11',opt,'-Wall','-Wextra','-Werror',
                '-I',str(ROOT/'firmware_common'),'-x','c','-','-o',str(exe)],
                input=code,text=True,capture_output=True)
            self.assertEqual(p.returncode,0,p.stdout+p.stderr)
            p=subprocess.run([str(exe)],text=True,capture_output=True)
            self.assertEqual(p.returncode,0,p.stdout+p.stderr)

    def test_only_task_admission_changes_all_control_and_fault_paths_identical(self):
        for name in ('FOC_CurrentLoopStep','FOC_EncoderSpeedUpdate','ProtectedLoop_TaskService',
            'ProtectedLoop_AdcIrq','ProtectedLoop_GuardIrqBody','ProtectedLoop_HealthCaptured',
            'ProtectedLoop_TimerHealthy','ProtectedLoop_GatesMatch','FaultDiag_CapturePacked',
            'ProtectedLoop_PwmEntry','ProtectedLoop_PwmStage','LatestOriginal_Admit',
            'PowerStage_Enable','PowerStage_Disable','MotorControl_SetIq','MotorControl_SetSpeed',
            'Encoder_ElectricalAngleRad','TighteningTask'):
            self.assertEqual(function(self.old,name),function(self.new,name),name)
        for basename in ('stm32g4xx_it.c.obj','foc_adc_timing_stm32.c.obj','as5047p_dma_stm32.c.obj',
                         'foc_zero_robust.c.obj','tightening_intent_fsm.c.obj','speed_scurve.c.obj',
                         'mechanical_identification.c.obj','speed_accel_feedforward.c.obj',
                         'speed_friction_compensation.c.obj'):
            self.assertEqual(next((ROOT/'foc2_app_a/build'/OLD).rglob(basename)).read_bytes(),
                next((ROOT/'foc2_app_a/build'/NEW).rglob(basename)).read_bytes(),basename)
        helper=function(self.new,'ProtectedLoop_AdcReady')
        self.assertLess(helper.index('volatile uint32_t'),helper.index('AS5047P_DmaNowUs'))
        self.assertIn('<=100U',helper)
        for forbidden in ('__disable_irq','__set_BASEPRI','while (','for ('):
            self.assertNotIn(forbidden,helper)

    def test_a_only_default_off_and_old_binary_and_b_unchanged(self):
        self.assertNotIn('FOC_READY_TIMESTAMP_SNAPSHOT',(ROOT/'foc2_app_b/CMakeLists.txt').read_text())
        cmake=(ROOT/'foc2_app_a/CMakeLists.txt').read_text()
        self.assertRegex(cmake,r'option\(FOC_READY_TIMESTAMP_SNAPSHOT "[^"]+" OFF\)')
        for preset,enabled in ((OLD,False),(NEW,True)):
            commands=json.loads((ROOT/'foc2_app_a/build'/preset/'compile_commands.json').read_text())
            cmd=next(c['command'] for c in commands if c['file'].endswith('/Core/Src/main.c'))
            self.assertEqual('-DFOC_READY_TIMESTAMP_SNAPSHOT=1 ' in cmd,enabled)
        for path,expected in (
            ('foc2_app_a/build/'+OLD+'/foc2.bin','e2f875992a94830d729155137d7aa70fee48feec6f801f61f3788c65db7b0e84'),
            ('foc2_app_b/build/MechanicalReviewB/foc2.bin','7ebdb56408baaa6c213c5dabe236250be673ed5a5c1345dfe64861d1e98dd366')):
            self.assertEqual(hashlib.sha256((ROOT/path).read_bytes()).hexdigest(),expected)

    def test_main_warning_set_not_increased(self):
        sets=[]
        for preset in (OLD,NEW):
            directory=ROOT/'foc2_app_a/build'/preset
            cmd=next(c['command'] for c in json.loads((directory/'compile_commands.json').read_text()) if c['file'].endswith('/Core/Src/main.c'))
            p=subprocess.run(re.sub(r' -o \S+ -c ',' -fsyntax-only ',cmd),cwd=directory,capture_output=True,text=True)
            self.assertEqual(p.returncode,0,p.stdout+p.stderr)
            sets.append(set(re.findall(r'warning: (.*)',p.stderr)))
        self.assertEqual(*sets)

    def test_arm_binary_loads_adc_reference_before_clock_read(self):
        elf=ROOT/'foc2_app_a/build'/NEW/'foc2.elf'
        p=subprocess.run(['D:/software/arm/bin/arm-none-eabi-objdump.exe','-d',
            '--disassemble=ProtectedLoop_Ready',str(elf)],capture_output=True,text=True,check=True)
        asm=p.stdout
        barrier=asm.index('dmb')
        call=asm.index('<__AS5047P_DmaNowUs_veneer>')
        self.assertLess(barrier,call)
        # ARM r4 holds the ADC reference across the clock function call.
        self.assertRegex(asm[:barrier].splitlines()[-2],r'ldr\s+r4, \[r2')
        self.assertRegex(asm[call:],r'subs\s+r2, r0, r4')
        self.assertIn('#100',asm[call:])
        sym=subprocess.run(['D:/software/arm/bin/arm-none-eabi-nm.exe','-S','-n',str(elf)],
            capture_output=True,text=True,check=True).stdout
        addr=re.search(r'^([0-9a-f]+) [0-9a-f]+ b cl_last_us$',sym,re.M).group(1)
        self.assertIn('.word\t0x'+addr,asm)


if __name__=='__main__':unittest.main()
