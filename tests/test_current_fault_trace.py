"""Offline diagnostics only; never imports a board test or opens hardware."""
import re
import subprocess
import sys
import unittest
import test_foc_fast_current_reject as fast

sys.path.insert(0,str(fast.ROOT/'tools'))
import current_fault_trace_report as report


class CurrentFaultTrace(unittest.TestCase):
    def test_default_off_and_explicit_zero_remove_entire_module(self):
        fast.OUT.mkdir(exist_ok=True)
        for flags in ([],['-DFOC_CURRENT_FAULT_TRACE_ENABLE=0']):
            obj=fast.OUT/('trace_disabled_'+str(len(flags))+'.o')
            fast.run(fast.ARM/'arm-none-eabi-gcc.exe','-std=c11','-Os','-Wall',
                '-Wextra','-Werror','-pedantic','-I',fast.COMMON,*flags,'-c',
                fast.COMMON/'foc_current_fault_trace.c','-o',obj)
            self.assertNotIn('foc_current_',fast.run(fast.ARM/'arm-none-eabi-nm.exe',obj))
        p=subprocess.run([str(fast.ARM/'arm-none-eabi-gcc.exe'),'-std=c11',
            '-I',str(fast.COMMON),'-DFOC_CURRENT_FAULT_TRACE_ENABLE=2','-fsyntax-only',
            str(fast.COMMON/'foc_current_fault_trace.c')],capture_output=True,text=True)
        self.assertNotEqual(p.returncode,0)
        self.assertIn('must be 0 or 1',p.stderr)

    def test_core_at_os_and_o2(self):
        for opt in ('-Os','-O2'):
            exe=fast.OUT/('current_fault_trace'+opt+'.exe')
            fast.run(fast.legacy.GCC,'-std=c11',opt,'-Wall','-Wextra','-Werror','-pedantic',
                '-UNDEBUG','-I',fast.COMMON,*fast.FLAGS,'-DFOC_CURRENT_FAULT_TRACE_ENABLE=1',
                '-DFOC_TRACE_HOST_TEST=1',fast.ROOT/'tests/foc_current_fault_trace_host.c',
                fast.COMMON/'foc_current_fault_trace.c','-o',exe)
            self.assertIn('PASS trace',fast.run(exe))

    def test_actual_adc_irq_with_trace_enabled(self):
        for opt in ('-Os','-O2'):
            exe=fast.OUT/('current_fault_trace_irq'+opt+'.exe')
            fast.run(fast.legacy.GCC,'-std=c11',opt,'-Wall','-Wextra','-Werror','-pedantic',
                '-UNDEBUG','-I',fast.COMMON,*fast.FLAGS,'-DFOC_CURRENT_FAULT_TRACE_ENABLE=1',
                '-DFOC_TRACE_HOST_TEST=1',fast.ROOT/'tests/foc_current_fault_trace_irq_host.c',
                fast.COMMON/'foc_current_fault_trace.c','-o',exe)
            self.assertIn('PASS actual IRQ trace',fast.run(exe))

    def test_trace_has_no_io_float_math_or_loops(self):
        text=(fast.COMMON/'foc_current_fault_trace.c').read_text('utf-8')
        code=re.sub(r'/\*.*?\*/','',text,flags=re.S)
        self.assertNotRegex(code,r'\b(?:for|while|printf|snprintf|malloc|calloc|free|UART_\w+)\s*\(')
        self.assertNotRegex(code,r'TIM1->\w+\s*=(?!=)')
        self.assertIn('FOC_TRACE_CALL(FocCurrentTrace_End());',
            (fast.COMMON/'protected_adc_irq.inc').read_text('utf-8'))

    def test_observational_equivalence_enabled_disabled(self):
        for opt in ('-Os','-O2'):
            results=[]
            for enabled in (0,1):
                exe=fast.OUT/f'current_trace_equivalence_{opt}_{enabled}.exe'
                extra=['-DFOC_CURRENT_FAULT_TRACE_ENABLE=1','-DFOC_TRACE_HOST_TEST=1',
                    fast.COMMON/'foc_current_fault_trace.c'] if enabled else []
                fast.run(fast.legacy.GCC,'-std=c11',opt,'-Wall','-Wextra','-Werror','-pedantic',
                    '-UNDEBUG','-I',fast.COMMON,*fast.FLAGS,*extra,
                    fast.ROOT/'tests/foc_current_fault_trace_equivalence.c','-o',exe)
                results.append(fast.run(exe))
            self.assertEqual(*results)

    def test_protection_precedes_discriminator_and_capture_precedes_return(self):
        text=(fast.COMMON/'foc_feedback_safety_candidate.h').read_text('utf-8')
        raw=text.index('FocOcConfirmResult result = FocFp_PushRawSafety')
        log=text.index('FOC_TRACE_CALL(FocCurrentTrace_Protection',raw)
        stop=text.index('if (result == FOC_OC_TRIPPED) return result;',raw)
        disc=text.index('int valid = FocCurrentValidation_Push',raw)
        self.assertLess(raw,log); self.assertLess(log,stop); self.assertLess(stop,disc)
        cold=(fast.COMMON/'protected_closed_loop.inc').read_text('utf-8')
        trip=cold.index('(void)FocFp_Trip(&cl_safety.protection,FOC_FP_HEALTH,0U);')
        capture=cold.index('FOC_TRACE_CALL(FocCurrentTrace_Protection(&cl_safety.protection));',trip)
        self.assertLess(cold.index('FocFeedbackGuard_OutputOff();'),trip)
        self.assertGreater(capture,trip) # shutdown before cold diagnostic hook

    def test_chronological_decoder_wrap_not_slot_zero(self):
        raw=bytearray(860)
        report.HEADER.pack_into(raw,0,0x43545231,0xffffffff,2,52,16,
            5,8,4,0,1,1,1,4,0,0,1,0)
        start=(5-8)&15
        for i in range(8):
            seq=(0xfffffffb+i)&0xffffffff
            values=[0]*len(report.NAMES)
            values[report.NAMES.index('seq')]=seq
            values[report.NAMES.index('sample_us')]=100+i*50
            values[report.NAMES.index('discriminator_result')]=-2
            if seq==0xffffffff: values[report.NAMES.index('events')]=1
            if seq==2: values[report.NAMES.index('protection_fault')]=1
            report.FRAME.pack_into(raw,28+((start+i)&15)*52,*values)
        t,rows=report.decode(raw)
        self.assertEqual([r['seq'] for r in rows],[0xfffffffb,0xfffffffc,0xfffffffd,
            0xfffffffe,0xffffffff,0,1,2])
        self.assertEqual(rows[0]['phase'],'PRE-4')
        self.assertEqual(rows[4]['phase'],'TRIGGER')
        self.assertEqual(rows[-1]['phase'],'FAULT')
        self.assertIn('NOT_EXECUTED',report.table(t,rows))
        self.assertIn('reconstructed',report.table(t,rows))
        self.assertEqual(report.FRAME.size,52)
        with self.assertRaises(ValueError): report.decode(raw[:-1])

    def test_actual_c_rolling_ring_decodes_before_state_and_final_fault(self):
        exe=fast.OUT/'rolling_trace_capture.exe'
        capture=fast.OUT/'rolling_trace_capture.bin'
        fast.run(fast.legacy.GCC,'-std=c11','-Os','-Wall','-Wextra','-Werror','-pedantic',
            '-UNDEBUG','-I',fast.COMMON,*fast.FLAGS,'-DFOC_CURRENT_FAULT_TRACE_ENABLE=1',
            '-DFOC_TRACE_HOST_TEST=1',fast.ROOT/'tests/foc_current_fault_trace_host.c',
            fast.COMMON/'foc_current_fault_trace.c','-o',exe)
        fast.run(exe,capture)
        raw=capture.read_bytes()
        self.assertEqual(len(raw),1172)
        t,rows=report.decode(raw)
        self.assertEqual(t['fault_seq'],rows[-1]['seq'])
        self.assertEqual(rows[-1]['seq']-rows[0]['seq'],15)
        self.assertGreater(rows[-1]['seq'],500000)
        self.assertEqual([r['unresolved_consecutive_before'] for r in rows[-3:]],[0,1,2])
        self.assertEqual([r['decision_path'] for r in rows[-3:]],[3,3,3])
        fault=rows[-1]
        self.assertEqual((fault['reference_u_before'],fault['candidate_u_before'],fault['raw_u']),
            (1564,1900,1200))
        self.assertEqual((fault['d_old'],fault['d_candidate']),(364,700))
        self.assertEqual(fault['discriminator_result'],-1)
        self.assertEqual(fault['pwm_pending_before'],2)
        text=report.table(t,rows)
        self.assertIn('FAULT/UNRESOLVED',text)
        self.assertIn('reference before',text)
        for broken in (raw[:-1],b'\x31'+raw[1:]):
            with self.assertRaises(ValueError): report.decode(broken)

    def test_before_capture_and_decision_precede_real_fault_latch(self):
        core=(fast.COMMON/'foc_feedback_safety_candidate.h').read_text('utf-8')
        begin=core.index('FocCurrentTrace_Begin(seq,now_us,raw_u,raw_v,s,angle)')
        disc=core.index('int valid = FocCurrentValidation_Push')
        decision=core.index('FOC_TRACE_CALL(FocCurrentTrace_Discriminator',disc)
        latch=core.index('FocFp_Trip(&s->protection,FOC_FP_CURRENT_INVALID',disc)
        freeze=core.index('FOC_TRACE_CALL(FocCurrentTrace_Protection',latch)
        self.assertLess(begin,disc)
        self.assertLess(disc,decision)
        self.assertLess(decision,latch)
        self.assertLess(latch,freeze)
        trace=(fast.COMMON/'foc_current_fault_trace.c').read_text('utf-8')
        self.assertIn('p->reason!=FOC_FP_CURRENT_INVALID',trace)
        self.assertEqual(trace.count('t->frozen=1U;'),1)
        self.assertNotIn('--t->post_remaining',trace)


if __name__=='__main__': unittest.main()
