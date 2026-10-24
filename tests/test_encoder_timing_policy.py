"""Separate transaction, schedule, freshness and control timing contracts."""
import hashlib
import subprocess
import unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
GCC=r'D:\Qt\Tools\mingw1310_64\bin\gcc.exe'


class EncoderTimingPolicyTests(unittest.TestCase):
    def compile_run(self,source,name,extra=()):
        for opt in ('-Os','-O2'):
            exe=ROOT/'tmp'/(name+opt+'.exe')
            p=subprocess.run([GCC,'-std=c11',opt,'-Wall','-Wextra','-Werror','-pedantic',
                '-DAS_DMA_TRANSACTION_US=400U','-DAS5047P_DMA_TIMING_POLICY_V2=1',
                '-I',str(ROOT/'firmware_common'),'-I',str(ROOT/'foc2_app_a/Core/Inc'),
                '-x','c','-',*map(str,extra),'-o',str(exe)],input=source,capture_output=True,text=True)
            self.assertEqual(p.returncode,0,p.stdout+p.stderr)
            p=subprocess.run([str(exe)],capture_output=True,text=True)
            self.assertEqual(p.returncode,0,p.stdout+p.stderr)

    def test_shared_consumer_classification_warning_and_age_boundaries(self):
        self.compile_run(r'''
#include <assert.h>
#include "as5047p_dma_engine.h"
#include "foc_encoder_timeout_diag.h"
int main(void){
 assert(AS_DMA_TRANSACTION_WARN_US==200 && AS_DMA_TRANSACTION_US==400);
 assert(AS_DMA_SCHEDULE_LATE_US==200 && AS_DMA_PERIOD_US==1000);
 assert(AS_DMA_SAMPLE_MAX_AGE_US==1500 && AS_DMA_CONTROL_WATCHDOG_US==2500);
 AsDmaTimingStats stats={0};uint32_t dt=0;
 for(unsigned elapsed=199;elapsed<=400;++elapsed){
  AsDmaCursor c={0};
  AsDmaSample s={.status=AS_DMA_OK,.sequence=1,.sample_us=100,.elapsed_us=elapsed};
  assert(AsDma_Consume(&c,&s,400,&dt)==(elapsed<400?1:-1));
  assert(FocEncoder_TimeoutReason(&c,&s,400)==(elapsed<400?FOC_TO_NONE:FOC_TO_ENCODER_TRANSACTION));
 }
 AsDmaSample s={.status=AS_DMA_OK,.sequence=1,.sample_us=100,.elapsed_us=203};
 AsDmaTiming_Record(&stats,&s);assert(stats.slow_count==1 && stats.ok_max_us==203);
 s.elapsed_us=199;AsDmaTiming_Record(&stats,&s);assert(stats.slow_count==1 && stats.ok_max_us==203);
 s.status=AS_DMA_PARITY;s.elapsed_us=350;AsDmaTiming_Record(&stats,&s);
 assert(stats.slow_count==1 && stats.ok_max_us==203);
 s.status=AS_DMA_OK;s.elapsed_us=203;
 AsDmaCursor c={0};assert(AsDma_Consume(&c,&s,1600,&dt)==1); /* age1500 allowed */
 assert(AsDma_Consume(&c,&s,1601,&dt)==-1); /* duplicate cannot refresh stale age */
 assert(FocEncoder_TimeoutReason(&c,&s,1601)==FOC_TO_ENCODER_SAMPLE);
 c=(AsDmaCursor){.valid=1,.sequence=1,.sample_us=100};s.sequence=2;s.sample_us=2601;
 assert(AsDma_Consume(&c,&s,2602,&dt)==-1);
 assert(FocEncoder_TimeoutReason(&c,&s,2602)==FOC_TO_ENCODER_INTERVAL);
 s.status=AS_DMA_CONTROL_STALE;assert(FocEncoder_TimeoutReason(&c,&s,2602)==FOC_TO_ENCODER_CONTROL);
 s.status=AS_DMA_PARITY;assert(AsDma_Consume(&c,&s,2602,&dt)==-1);
 assert(FocEncoder_TimeoutReason(&c,&s,2602)==FOC_TO_NONE); /* not mislabeled timeout */
 c=(AsDmaCursor){0};s=(AsDmaSample){.status=AS_DMA_OK,.sequence=9,
     .sample_us=0xfffffff0U,.elapsed_us=203};
 assert(AsDma_Consume(&c,&s,0x10U,&dt)==1);
 return 0;}
''','encoder-timing-policy-consume',(ROOT/'firmware_common/as5047p_dma_engine.c',))

    def test_real_deferred_protocol_hard_deadline_schedule_and_terminal_fix(self):
        src='#define AS5047P_DMA_TERMINAL_FIX 1\n'+(ROOT/'tests/as5047p_host/deferred_test.c').read_text()
        src=src.replace('for (unsigned i=0;i<201U;++i) Step(0U);',
                        'for (unsigned i=0;i<=AS_DMA_TRANSACTION_US;++i) Step(0U);')
        src=src.replace('int main(void)','static int baseline_main(void)')
        pos=src.rfind('}');src=src[:pos]+'return 0;\n'+src[pos:]
        src+=r'''
int main(void){
 CHECK(baseline_main()==0); /* Existing protocol/delayed service/errors/control guard. */
 /* Latest board frame: final HOLD guard due201, deadline now400. */
 Init();engine.state=AS_DMA_HOLD;engine.frame=1;engine.rx=0x892a;
 engine.word_rx_us=154;engine.guard_us=201;timer.CNT=203;
 AsDma_Guard(&engine,203);
 CHECK(engine.sample.status==AS_DMA_OK && engine.sample.elapsed_us==203);
 CHECK(engine.successes==1 && engine.failures==0);
 AsDmaTimingStats stats={0};AsDmaTiming_Record(&stats,&engine.sample);
 CHECK(stats.slow_count==1 && stats.ok_max_us==203);
 timer.CNT=400;DeferTimerTop();TIM6_DAC_IRQHandler();
 CHECK(!defer_urgent && engine.successes==1 && engine.failures==0);
 /* A real incomplete transaction at400 still closes BEFORE bottom half. */
 Init();timer.CNT=400;pwm.BDTR=TIM_BDTR_MOE;DeferTimerTop();
 CHECK(defer_urgent==AS_DMA_TIMEOUT && !(pwm.BDTR&TIM_BDTR_MOE));
 TIM6_DAC_IRQHandler();CHECK(engine.sample.status==AS_DMA_TIMEOUT);
 /* Schedule late200 must NOT inherit the relaxed transaction deadline400. */
 Init();for(unsigned k=0;k<30;++k)Step(1);
 timer.CNT=next_period_us+199;TIM6_DAC_IRQHandler();
 CHECK(engine.state!=AS_DMA_IDLE && engine.attempts==2 && engine.sample.status==AS_DMA_OK);
 Init();for(unsigned k=0;k<30;++k)Step(1);
 timer.CNT=next_period_us+200;TIM6_DAC_IRQHandler();
 CHECK(engine.sample.status==AS_DMA_SCHEDULE && !periodic);
 puts("PASS encoder timing: completed203 warns; incomplete400 stops; schedule200 preserved");
 return 0;
}
#define AS_DMA_TERMINAL_CLAIM(e,status,now) DeferTerminalClaim(status,now)
#define AS_DMA_BEGIN_ALLOWED(e) DeferBeginAllowed()
#include "as5047p_dma_engine.c"
'''
        self.compile_run(src,'encoder-timing-policy-deferred')

    def test_foreground_explicit_policy_log(self):
        text=(ROOT/'tests/test_motor_identification.py').read_text()
        start=text.index("code=r'''",text.index('def test_real_binding_'))+len("code=r'''")
        src='#include "as5047p_dma_engine.h"\n'+text[start:text.index("'''",start)]
        src=src.replace('#include "motor_identification_binding.inc"',
            'static void AS5047P_DmaGetTimingStats(uint32_t *n,uint32_t *m){*n=4;*m=203;}\n'
            '#include "motor_identification_binding.inc"')
        src=src.replace('assert(motor_ident.used && !critical);',r'''
 assert(motor_ident.used && !critical);
 MotorIdent_Command("MOTOR TEST IDENT ENCODER TIME",out,sizeof out);
 assert(strstr(out,"POLICY=2 WARN_US=200 DEADLINE_US=400 SCHED_US=200 PERIOD_US=1000 AGE_US=1500 CONTROL_US=2500 SLOW_N=4 OK_MAX_US=203"));
''')
        self.compile_run(src,'encoder-timing-policy-log')

    def test_frozen_control_and_old_images(self):
        import re
        from test_torque_chain import FROZEN,function
        from test_torque350_five_second import expanded
        a=expanded('a','MotorParameterIdentificationEncoderTerminalDiagnostic')
        b=expanded('a','MotorParameterIdentificationEncoderTimingDiagnostic')
        for name in set(FROZEN+('FOC_CurrentLoopStep','FOC_EncoderSpeedUpdate','ProtectedLoop_Stop',
                              'ProtectedLoop_PwmEntry','ProtectedLoop_PwmStage')):
            self.assertEqual(re.sub(r'\s+','',function(a,name)),re.sub(r'\s+','',function(b,name)),name)
        for path,sha in (
            ('foc2_app_a/build/MotorParameterIdentificationEncoderTerminalDiagnostic/foc2.bin',
             '2e0661646b6bedc372c7d7f4209e4dc4f5279f23a1082f0d9992c680b11c7b2f'),
            ('foc2_app_b/build/FrictionBUnchanged/foc2.bin',
             '7ebdb56408baaa6c213c5dabe236250be673ed5a5c1345dfe64861d1e98dd366')):
            self.assertEqual(hashlib.sha256((ROOT/path).read_bytes()).hexdigest(),sha)


if __name__=='__main__':unittest.main()
