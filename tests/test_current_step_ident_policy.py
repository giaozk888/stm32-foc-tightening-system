"""Current-step adaptation of the existing identification timing policy, OFFLINE."""
import hashlib
import json
import re
import subprocess
import unittest
from pathlib import Path
import test_current_step_ab as step
import test_encoder_timing_policy as policy

ROOT=Path(__file__).resolve().parents[1]
BUILD=ROOT/'foc2_app_a/build/CurrentStepAbIdentPolicy'

class StepIdentPolicyTests(unittest.TestCase):
    def test_sample_skips_are_counted_not_a_cumulative_abort(self):
        src=(ROOT/'tests/current_step_ab_host.c').read_text()
        src=src.replace('puts("PASS current step AB:',r'''
    s=fresh();tick(&s,0U,0);
    for(uint32_t t=100U;t<=10000U;t+=100U)tick(&s,t,0);
    assert(s.state==CS_ACTIVE && s.metrics[0].gaps==100U);
    /* Skip accounting never fabricates a pulse observation. */
    assert(!s.metrics[0].high_n);
    CurrentStep_Record(&s,s.start_us+10050U,202U,0,0,0,0,0,0,0,0,0,0,0,32U);
    assert(s.state==CS_ABORT && s.reason==CS_PROTECTION && s.failure.fault==32U);
    puts("PASS current step AB:''')
        out=ROOT/'tmp/current-step-policy-host';out.mkdir(exist_ok=True)
        for opt in ('-Os','-O2'):
            exe=out/f'skips-{opt}.exe'
            p=subprocess.run([str(step.pi.GCC),'-std=c11',opt,'-Wall','-Wextra','-Werror',
                '-I',str(ROOT/'firmware_common'),'-x','c','-',
                str(ROOT/'firmware_common/current_step_ab.c'),'-lm','-o',str(exe)],
                input=src,capture_output=True,text=True)
            self.assertEqual(p.returncode,0,p.stderr)
            p=subprocess.run([str(exe)],capture_output=True,text=True)
            self.assertEqual(p.returncode,0,p.stdout+p.stderr)

    def test_real_deferred_word201_is_not_fault_but_incomplete400_still_is(self):
        src='#define AS5047P_DMA_TERMINAL_FIX 1\n'+(ROOT/'tests/as5047p_host/deferred_test.c').read_text()
        # Keep and run all original protocol/error/cancellation tests with the
        # selected policy deadline, then add the observed WORD/frame1 case.
        src=src.replace('for (unsigned i=0;i<201U;++i) Step(0U);',
                        'for (unsigned i=0;i<=AS_DMA_TRANSACTION_US;++i) Step(0U);')
        src=src.replace('int main(void)','static int baseline_main(void)')
        pos=src.rfind('}');src=src[:pos]+'return 0;\n'+src[pos:]
        src+=r'''
int main(void){
 CHECK(baseline_main()==0);
 Init();engine.state=AS_DMA_WORD;engine.frame=1;engine.rx=0x892a;
 timer.CNT=201;DeferTimerTop();
 CHECK(!defer_urgent && engine.state==AS_DMA_WORD && engine.failures==0);
 /* A completed final word is then processed through the actual top/bottom
  * halves; not fabricated as successful merely because NDTR reached zero. */
 DMA1->ISR=DMA_ISR_TCIF4;DeferRxTop();TIM6_DAC_IRQHandler();
 for(unsigned k=0;k<15;++k)Step(1);
 CHECK(engine.sample.status==AS_DMA_OK && engine.sample.elapsed_us>=200 &&
       engine.sample.elapsed_us<400 && engine.successes==1 && !engine.failures);
 AsDmaTimingStats stats={0};AsDmaTiming_Record(&stats,&engine.sample);
 CHECK(stats.slow_count==1 && stats.ok_max_us==engine.sample.elapsed_us);
 Init();timer.CNT=400;pwm.BDTR=TIM_BDTR_MOE;DeferTimerTop();
 CHECK(defer_urgent==AS_DMA_TIMEOUT && !(pwm.BDTR&TIM_BDTR_MOE));
 TIM6_DAC_IRQHandler();CHECK(engine.sample.status==AS_DMA_TIMEOUT);
 puts("PASS observed WORD201: accepted only after completion; incomplete400 remains OFF");
 return 0;
}
#define AS_DMA_TERMINAL_CLAIM(e,status,now) DeferTerminalClaim(status,now)
#define AS_DMA_BEGIN_ALLOWED(e) DeferBeginAllowed()
#include "as5047p_dma_engine.c"
'''
        policy.EncoderTimingPolicyTests().compile_run(src,'step-ident-observed-word201')

    def test_actual_foreground_policy_command(self):
        out=ROOT/'tmp/current-step-policy-host';out.mkdir(exist_ok=True)
        binding=(ROOT/'firmware_common/current_step_ab_binding.inc').read_text()
        binding=binding[:binding.index('__attribute__((optimize("Os")))\nstatic void TighteningTask')]
        (out/'current_step_ab_test_binding.inc').write_text(binding,encoding='utf-8')
        src='''#include "as5047p_dma_engine.h"
#define FOC_CURRENT_STEP_IDENT_POLICY 1
#define AS5047P_DMA_TERMINAL_FIX 1
static void AS5047P_DmaGetTimingStats(uint32_t *n,uint32_t *m){*n=3;*m=215;}
'''+(ROOT/'tests/current_step_ab_binding_host.c').read_text()
        src=src.replace('char out[384];',r'''char out[384];
 CHECK(CurrentStep_Command("MOTOR TEST CURRENT STEP ENCODER TIME",out,sizeof out));
 CHECK(strstr(out,"POLICY=2 TERMINAL_FIX=1 WARN_US=200 DEADLINE_US=400 SCHED_US=200 PERIOD_US=1000 AGE_US=1500 CONTROL_US=2500 SLOW_N=3 OK_MAX_US=215"));
''')
        for opt in ('-Os','-O2'):
            exe=out/f'policy-{opt}.exe'
            p=subprocess.run([str(step.pi.GCC),'-std=c11',opt,'-Wall','-Wextra','-Werror',
                '-Wno-unused-function','-Wno-unused-variable','-DAS_DMA_TRANSACTION_US=400U',
                '-DAS5047P_DMA_TIMING_POLICY_V2=1','-I',str(out),'-I',str(ROOT/'firmware_common'),
                '-x','c','-',str(ROOT/'firmware_common/current_step_ab.c'),'-o',str(exe)],
                input=src,capture_output=True,text=True)
            self.assertEqual(p.returncode,0,p.stderr)
            p=subprocess.run([str(exe)],capture_output=True,text=True)
            self.assertEqual(p.returncode,0,p.stdout+p.stderr)

    def test_no_control_protection_adc_pipeline_or_irq_changes(self):
        old=step.expanded('a','CurrentStepAbGateEvidence')
        new=step.expanded('a','CurrentStepAbIdentPolicy')
        for name in ('FOC_CurrentLoopStep','FOC_EncoderSpeedUpdate','ProtectedLoop_GatesObserved',
            'ProtectedLoop_EmergencyOff','ProtectedLoop_Stop','ProtectedLoop_TimerHealthy',
            'ProtectedLoop_PwmEntry','ProtectedLoop_PwmStage','ProtectedLoop_PwmCommitPermit',
            'ProtectedLoop_Pair','ProtectedLoop_TaskService','FocCurrentValidation_Push',
            'FOC_ResetController','CurrentStep_FocReference','CurrentStep_Capture'):
            self.assertEqual(step.function(old,name),step.function(new,name),name)
        commands=json.loads((BUILD/'compile_commands.json').read_text())
        for ending in ('/Core/Src/main.c','/as5047p_dma_stm32.c'):
            command=next(x['command'] for x in commands if x['file'].endswith(ending))
            for flag in ('AS5047P_DMA_TERMINAL_FIX=1','AS5047P_DMA_TIMING_POLICY_V2=1',
                         'AS_DMA_TRANSACTION_US=400U','FOC_CURRENT_STEP_IDENT_POLICY=1'):
                self.assertEqual(command.count('-D'+flag),1)
            self.assertNotIn('-DFOC_MOTOR_IDENTIFICATION_DIAG=1',command)
        self.assertNotIn('CurrentStep_',step.expanded('b','CurrentPiBUnchanged'))

    def test_old_images_remain_pinned_and_no_new_warnings(self):
        expected={
            'a/build/CurrentStepAbGateEvidence':'9cb14e996ca42fddb6608d90d8eb7d3ea3aef9b58b31b78431c285a5222a2fb1',
            'a/build/CurrentStepAbDiagnostic':'d7b3dd465a113d1f7efcec85fcd472bd8706dbb34566317c5f4ef6b82c2ec9eb',
            'a/build/CurrentPiIdentifiedCandidate':'aaeee6b02372f9ecac2d8ec0ecb171f17bf87df41e54f43fe52b4ec9d404b56e',
            'b/build/FrictionBUnchanged':'7ebdb56408baaa6c213c5dabe236250be673ed5a5c1345dfe64861d1e98dd366'}
        for directory,digest in expected.items():
            self.assertEqual(hashlib.sha256((ROOT/('foc2_app_'+directory)/'foc2.bin').read_bytes()).hexdigest(),digest)
        for source in ('/Core/Src/main.c','/as5047p_dma_stm32.c'):
            warnings=[]
            for name in ('CurrentStepAbGateEvidence','CurrentStepAbIdentPolicy'):
                directory=BUILD.parent/name
                command=next(x['command'] for x in json.loads((directory/'compile_commands.json').read_text())
                             if x['file'].endswith(source))
                command=re.sub(r' -o \S+ -c ',' -fsyntax-only ',command)
                p=subprocess.run(command,cwd=directory,capture_output=True,text=True)
                self.assertEqual(p.returncode,0,p.stderr)
                warnings.append(set(re.findall(r'warning: (.*)',p.stderr)))
            self.assertFalse(warnings[1]-warnings[0],warnings[1]-warnings[0])

if __name__=='__main__':unittest.main()
