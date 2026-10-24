"""Opt-in terminal arbitration: real port deferred service + engine, no devices."""
import hashlib
import re
import subprocess
import unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
GCC=r'D:\Qt\Tools\mingw1310_64\bin\gcc.exe'


class EncoderTerminalFixTests(unittest.TestCase):
    def test_real_engine_deadline_interleavings_generic_and_fixed_ops(self):
        source=(ROOT/'tests/as5047p_host/deferred_test.c').read_text()
        source='#define AS5047P_DMA_TERMINAL_FIX 1\n'+source
        source=source.replace('#define __DMB() ((void)0)',
            'static void TestBarrier(void);\n#define __DMB() TestBarrier()')
        source=source.replace('static void StopWord(void *context) { (void)context; DMA1->ISR=0U; }',r'''
static unsigned inject_cleanup,inject_barrier,inject_control;
static unsigned collect_terminal,terminal_count;
static AsDmaSample terminals[3];
static void DeferTimerTop(void);
static void StopWord(void *context) {
 (void)context;DMA1->ISR=0U;
 if(inject_cleanup){inject_cleanup=0;timer.CNT=200;DeferTimerTop();}
}
''')
        source=source.replace('(void)p; ++finishes; timer.DIER&=~4U;',r'''
 (void)p; ++finishes; timer.DIER&=~4U;
 if(collect_terminal && terminal_count<3)terminals[terminal_count++]=engine.sample;
''')
        source=source.replace('int main(void)','static int baseline_main(void)')
        pos=source.rfind('}');source=source[:pos]+'return 0;\n'+source[pos:]
        source+=r'''
static void TestBarrier(void){
 if(inject_barrier && !--inject_barrier){
  timer.CNT=200;
  if(inject_control)control_due_us=200;
  DeferTimerTop();
 }
}
static void AtFinalFrame(void){
 collect_terminal=inject_cleanup=inject_barrier=inject_control=0;
 Init();engine.state=AS_DMA_HOLD;engine.frame=1;
 engine.rx=0x892a;engine.word_rx_us=155;engine.guard_us=197;
 timer.CNT=199;terminal_count=0;collect_terminal=1;
 pwm.BDTR=TIM_BDTR_MOE;gpio.BSRR=DRIVER_SD_Pin;
}
int main(void){
 CHECK(baseline_main()==0); /* Original protocol/error/stale/35us FOC blackouts. */
 /* Timer at200 interrupts cleanup after pre-deadline completion is claimed. */
 AtFinalFrame();inject_cleanup=1;AsDma_Guard(&engine,199);
 CHECK(!defer_urgent && engine.sample.status==AS_DMA_OK && terminal_count==1);
 CHECK(engine.sample.elapsed_us==199 && engine.successes==1 && !engine.failures);
 CHECK(pwm.BDTR&TIM_BDTR_MOE);
 timer.CNT=202;TIM6_DAC_IRQHandler();CHECK(terminal_count==1 && !off_seen);
 CHECK(engine.attempts==1 && engine.successes==1 && engine.failures==0);
 /* New transaction has its own active deadline, not the old success claim. */
 CHECK(AsDma_Begin(&engine,0x3fff,1000));CHECK(!defer_terminal_claimed);
 timer.CNT=1200;DeferTimerTop();CHECK(defer_urgent==AS_DMA_TIMEOUT);
 CHECK(!(pwm.BDTR&TIM_BDTR_MOE));
 TIM6_DAC_IRQHandler();CHECK(engine.sample.status==AS_DMA_TIMEOUT && terminal_count==2);
 CHECK(!AsDma_Begin(&engine,0x3fff,1300)); /* No implicit fault recovery. */
 /* Timer wins BEFORE claim: must never publish success or reopen outputs. */
 AtFinalFrame();inject_barrier=1;AsDma_Guard(&engine,199);
 CHECK(defer_urgent==AS_DMA_TIMEOUT && engine.sample.status==AS_DMA_TIMEOUT);
 CHECK(!engine.successes && engine.failures==1 && terminal_count==1);
 CHECK(engine.sample.completed_us==200 && !(pwm.BDTR&TIM_BDTR_MOE));
 timer.CNT=202;TIM6_DAC_IRQHandler();CHECK(terminal_count==1 && !(pwm.BDTR&TIM_BDTR_MOE));
 /* Timer AFTER claim: no duplicate transaction timeout. */
 AtFinalFrame();inject_barrier=2;AsDma_Guard(&engine,199);
 CHECK(!defer_urgent && terminal_count==1 && engine.sample.status==AS_DMA_OK);
 CHECK(pwm.BDTR&TIM_BDTR_MOE);
 /* Live clock at deadline rejects an old now=199 argument: no backdating. */
 AtFinalFrame();timer.CNT=200;AsDma_Guard(&engine,199);
 CHECK(engine.sample.status==AS_DMA_TIMEOUT && !engine.successes && terminal_count==1);
 CHECK(!(pwm.BDTR&TIM_BDTR_MOE));
 /* Independent control stale remains effective even after completion claim. */
 AtFinalFrame();inject_control=1;inject_barrier=2;AsDma_Guard(&engine,199);
 CHECK(defer_urgent==AS_DMA_CONTROL_STALE && engine.sample.status==AS_DMA_CONTROL_STALE);
 CHECK(!engine.successes && terminal_count==1 && !(pwm.BDTR&TIM_BDTR_MOE));
 /* Existing IO fault wins before completion; not swallowed as late timer. */
 AtFinalFrame();DeferOff(AS_DMA_IO);AsDma_Guard(&engine,199);
 CHECK(engine.sample.status==AS_DMA_IO && !engine.successes && terminal_count==1);
 CHECK(!(pwm.BDTR&TIM_BDTR_MOE));
 timer.CNT=202;TIM6_DAC_IRQHandler();CHECK(terminal_count==1);
 /* Same pre/post boundary semantics across the 32-bit microsecond wrap. */
 AtFinalFrame();engine.started_us=0xffffff80U;engine.deadline_us=72;
 engine.guard_us=69;engine.word_rx_us=27;timer.CNT=71;
 AsDma_Guard(&engine,71);
 CHECK(engine.sample.status==AS_DMA_OK && engine.sample.elapsed_us==199 && terminal_count==1);
 AtFinalFrame();engine.started_us=0xffffff80U;engine.deadline_us=72;
 engine.guard_us=69;engine.word_rx_us=27;timer.CNT=72;
 AsDma_Guard(&engine,71);
 CHECK(engine.sample.status==AS_DMA_TIMEOUT && engine.sample.elapsed_us==200 && terminal_count==1);
 puts("PASS terminal arbitration: completion199/timeout200/cleanup202, real late/IO/control/new epoch");
 return 0;
}
#define AS_DMA_TERMINAL_CLAIM(e,status,now) DeferTerminalClaim(status,now)
#define AS_DMA_BEGIN_ALLOWED(e) DeferBeginAllowed()
'''
        for fixed in (False,True):
            bind=r'''
#define AS_DMA_BIND_cs Cs
#define AS_DMA_BIND_guard Guard
#define AS_DMA_BIND_deadline Deadline
#define AS_DMA_BIND_start_word Start
#define AS_DMA_BIND_stop_word StopWord
#define AS_DMA_BIND_busy Busy
#define AS_DMA_BIND_finish Finish
#define AS_DMA_BIND_fault_snapshot Fault
#define AS_DMA_BIND(name,e) AS_DMA_BIND_##name
#define AS_DMA_HAS_FAULT_SNAPSHOT(e) 1
''' if fixed else ''
            full=source+bind+'\n#include "as5047p_dma_engine.c"\n'
            for opt in ('-Os','-O2'):
                exe=ROOT/'tmp'/('encoder-terminal-fix-'+str(fixed)+opt+'.exe')
                p=subprocess.run([GCC,'-std=c11',opt,'-Wall','-Wextra','-Werror','-pedantic',
                    '-I',str(ROOT/'firmware_common'),'-I',str(ROOT/'foc2_app_a/Core/Inc'),
                    '-x','c','-','-o',str(exe)],input=full,capture_output=True,text=True)
                self.assertEqual(p.returncode,0,p.stdout+p.stderr)
                p=subprocess.run([str(exe)],capture_output=True,text=True)
                self.assertEqual(p.returncode,0,p.stdout+p.stderr)
                self.assertIn('PASS terminal arbitration',p.stdout)

    def test_thresholds_foc_irq_pipeline_and_previous_pins_unchanged(self):
        from test_torque_chain import FROZEN,function
        from test_torque350_five_second import expanded
        old=expanded('a','MotorParameterIdentificationRsRejectOnlyDiagnostic')
        new=expanded('a','MotorParameterIdentificationEncoderTerminalDiagnostic')
        for name in set(FROZEN+('FOC_CurrentLoopStep','FOC_EncoderSpeedUpdate','ProtectedLoop_Stop',
                              'ProtectedLoop_PwmEntry','ProtectedLoop_PwmStage')):
            self.assertEqual(re.sub(r'\s+','',function(old,name)),re.sub(r'\s+','',function(new,name)),name)
        for key,value in (('TRANSACTION',200),('GUARD',2),('PERIOD',1000),
                          ('SAMPLE_MAX_AGE',1500),('CONTROL_WATCHDOG',2500)):
            self.assertRegex((ROOT/'firmware_common/as5047p_timing_policy.h').read_text(),
                             rf'AS_DMA_{key}_US\s+{value}U')
        port=(ROOT/'firmware_common/as5047p_dma_stm32.c').read_text()
        self.assertIn('HAL_NVIC_SetPriority(TIM6_DAC_IRQn,4U,0U)',port)
        self.assertIn('#define AS_DMA_IRQ_PRIORITY 3U',port)
        for path,sha in (
            ('foc2_app_a/build/MotorParameterIdentificationRsRejectOnlyDiagnostic/foc2.bin',
             'c0be6a0d65a1aefa52e30b4b036005ab8787ea96be5f4f720b723f61f820d9d4'),
            ('foc2_app_b/build/FrictionBUnchanged/foc2.bin',
             '7ebdb56408baaa6c213c5dabe236250be673ed5a5c1345dfe64861d1e98dd366')):
            self.assertEqual(hashlib.sha256((ROOT/path).read_bytes()).hexdigest(),sha)


if __name__=='__main__':unittest.main()
