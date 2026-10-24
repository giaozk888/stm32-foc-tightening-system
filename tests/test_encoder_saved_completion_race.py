"""Diagnosis only: replay completion/deadline preemption, no firmware fix."""
import subprocess
import sys
import unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
import encoder_saved_fault_report as report
GCC=r'D:\Qt\Tools\mingw1310_64\bin\gcc.exe'


class SavedCompletionRaceTests(unittest.TestCase):
    def test_fixed_board_run_has_real_hold_timeout_not_duplicate_success(self):
        r=report.decode(ROOT/'tmp/motor-ident-rs50-run-1792502267845988100.json',
            ROOT/'foc2_app_a/build/MotorParameterIdentificationEncoderTerminalDiagnostic/foc2.elf')
        self.assertFalse(r['same_attempt_success_then_timeout'])
        self.assertEqual(r['first_fault']['phase'],4)
        self.assertEqual(r['fault_elapsed_us'],203)
        self.assertEqual(r['first_fault']['guard_us']-r['first_fault']['started_us'],201)
        self.assertEqual(r['engine']['attempts'],r['engine']['successes']+r['engine']['failures'])
        self.assertIsNone(r['success_margin_us'])

    def test_saved_199us_success_then_202us_timeout(self):
        r=report.decode(ROOT/'tmp/motor-ident-rs50-run-1792501108997244100.json',
            ROOT/'foc2_app_a/build/MotorParameterIdentificationRsRejectOnlyDiagnostic/foc2.elf')
        self.assertTrue(r['same_attempt_success_then_timeout'])
        self.assertEqual(r['first_fault']['phase'],0)
        self.assertEqual(r['fault_elapsed_us'],202)
        self.assertEqual(r['success_margin_us'],1)
        self.assertEqual(r['counters']['dma_errors'],0)
        self.assertEqual(r['counters']['defer_urgent'],2)

    def test_production_engine_and_deferred_service_reproduce_duplicate_terminal(self):
        # Preserve/run the full original fixture, then inject one high-priority
        # timer event in Complete's StopWord hook at the 200us boundary.
        # Simulation is an interleaving proof, NOT board WCET/IRQ trace evidence.
        source=(ROOT/'tests/as5047p_host/deferred_test.c').read_text()
        source=source.replace('static void StopWord(void *context) { (void)context; DMA1->ISR=0U; }',r'''
static unsigned inject_completion_boundary,collect_terminal,terminal_count;
static AsDmaSample terminals[2];
static AsDmaState failure_phase;
static void DeferTimerTop(void);
static void StopWord(void *context) {
 (void)context; DMA1->ISR=0U;
 if(inject_completion_boundary){
  inject_completion_boundary=0U;timer.CNT=200U;DeferTimerTop();
 }
}
''')
        source=source.replace('(void)p; ++finishes; timer.DIER&=~4U;',r'''
 (void)p; ++finishes; timer.DIER&=~4U;
 if(collect_terminal && terminal_count<2U)terminals[terminal_count++]=engine.sample;
''')
        source=source.replace('(void)p; (void)e; (void)s; (void)now; off_seen=1U;',
            '(void)p; (void)s; (void)now; off_seen=1U;failure_phase=e->state;')
        source=source.replace('int main(void)','static int baseline_main(void)')
        # Existing fixture main has implicit main return; renamed baseline needs
        # an explicit return under -Werror.
        pos=source.rfind('}')
        source=source[:pos]+'return 0;\n'+source[pos:]
        source+=r'''
int main(void){
 CHECK(baseline_main()==0);
 Init();engine.state=AS_DMA_HOLD;engine.frame=1U;
 engine.rx=0x892aU;engine.word_rx_us=155U;engine.guard_us=197U;
 timer.CNT=199U;inject_completion_boundary=1U;collect_terminal=1U;
 AsDma_Guard(&engine,199U);
 CHECK(engine.state==AS_DMA_IDLE && engine.sample.status==AS_DMA_OK);
 CHECK(engine.successes==1U && engine.failures==0U);
 CHECK(defer_urgent==AS_DMA_TIMEOUT && terminal_count==1U);
 CHECK(terminals[0].elapsed_us==199U && terminals[0].sequence==1U);
 timer.CNT=202U;TIM6_DAC_IRQHandler();
 CHECK(failure_phase==AS_DMA_IDLE && terminal_count==2U);
 CHECK(terminals[1].status==AS_DMA_TIMEOUT && terminals[1].elapsed_us==202U);
 CHECK(engine.attempts==1U && engine.successes==1U && engine.failures==1U);
 CHECK(terminals[1].sequence==2U && terminals[1].sample_us==terminals[0].sample_us);
 puts("REPRODUCED: same attempt success199 -> timeout202, failure phase IDLE; no production fix");
 return 0;
}
'''
        for opt in ('-Os','-O2'):
            exe=ROOT/'tmp'/('encoder-completion-race'+opt+'.exe')
            p=subprocess.run([GCC,'-std=c11',opt,'-Wall','-Wextra','-Werror','-pedantic',
                '-I',str(ROOT/'firmware_common'),'-I',str(ROOT/'foc2_app_a/Core/Inc'),'-x','c','-',
                str(ROOT/'firmware_common/as5047p_dma_engine.c'),'-o',str(exe)],
                input=source,capture_output=True,text=True)
            self.assertEqual(p.returncode,0,p.stdout+p.stderr)
            p=subprocess.run([str(exe)],capture_output=True,text=True)
            self.assertEqual(p.returncode,0,p.stdout+p.stderr)
            self.assertIn('REPRODUCED',p.stdout)


if __name__=='__main__':unittest.main()
