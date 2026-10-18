"""One-cycle hard-off preparation only: no device or boot access."""
import json
import re
import struct
import subprocess
import sys
import unittest
import test_foc_preempt_commit_probe as pre
import test_foc_rc_protected_candidate as rc

fast=pre.fast
ROOT=fast.ROOT
FLAGS=pre.FLAGS+['-DFOC_ONE_CYCLE_PWM_PIPELINE=1']

class PwmPipelineTests(unittest.TestCase):
    def test_real_irq_invalid_path_freezes_pi(self):
        for opt in ('-Os','-O2'):
            exe=fast.OUT/('pwm_pipeline_freeze'+opt+'.exe')
            # Exercise the real IRQ body with the new hold bookkeeping. The
            # preemption/commit adapter is independently exercised below.
            fast.run(fast.legacy.GCC,'-std=c11',opt,'-Wall','-Wextra','-Werror','-pedantic',
                '-UNDEBUG','-I',fast.COMMON,*fast.FLAGS,'-DFOC_ONE_CYCLE_PWM_PIPELINE=1',
                ROOT/'tests/foc_fast_reject_irq_host.c','-o',exe)
            self.assertIn('PASS actual ADC IRQ',fast.run(exe))
            confirm=fast.OUT/('pwm_pipeline_cur_confirm'+opt+'.exe')
            fast.run(fast.legacy.GCC,'-std=c11',opt,'-Wall','-Wextra','-Werror','-pedantic',
                '-UNDEBUG','-I',fast.COMMON,*FLAGS,
                ROOT/'tests/foc_cur_confirm_cycles_host.c','-o',confirm)
            self.assertIn('PASS CUR_CONFIRM cycles',fast.run(confirm))

    def test_lower_priority_guard_attribution(self):
        for opt in ('-Os','-O2'):
            exe=fast.OUT/('pwm_pipeline_irq'+opt+'.exe')
            fast.run(fast.legacy.GCC,'-std=c11',opt,'-Wall','-Wextra','-Werror','-pedantic',
                '-UNDEBUG','-I',ROOT/'tests/foc_preempt_mock','-I',fast.COMMON,*FLAGS,
                fast.COMMON/'foc_preempt_probe_stm32.c',
                ROOT/'tests/foc_pwm_pipeline_attribution_host.c','-o',exe)
            self.assertIn('PASS lower TIM7',fast.run(exe))

    def test_actual_binding_epochs_hold_and_next_cycle(self):
        for opt in ('-Os','-O2'):
            exe=fast.OUT/('pwm_pipeline_binding'+opt+'.exe')
            fast.run(fast.legacy.GCC,'-std=c11',opt,'-Wall','-Wextra','-Werror','-pedantic',
                '-UNDEBUG','-I',fast.COMMON,*FLAGS,
                ROOT/'tests/foc_pwm_pipeline_binding_host.c',
                fast.COMMON/'foc_current_zero.c',fast.COMMON/'foc_zero_median.c',
                fast.COMMON/'foc_zero_robust.c','-o',exe)
            self.assertIn('PASS pipeline actual binding',fast.run(exe))

    def test_actual_noninvasive_commit(self):
        for opt in ('-Os','-O2'):
            exe=fast.OUT/('pwm_pipeline_commit'+opt+'.exe')
            fast.run(fast.legacy.GCC,'-std=c11',opt,'-Wall','-Wextra','-Werror','-pedantic',
                '-UNDEBUG','-I',ROOT/'tests/foc_preempt_mock','-I',fast.COMMON,
                *rc.ADAPTER_FLAGS,*FLAGS,fast.COMMON/'foc_adc_window.c',
                fast.COMMON/'foc_adc_raw_buffer.c',fast.COMMON/'foc_adc_timing_stm32.c',
                ROOT/'tests/foc_pwm_pipeline_commit_host.c','-o',exe)
            for case in range(15):
                with self.subTest(opt=opt,case=case):
                    self.assertIn('PASS pipeline actual CCR',fast.run(exe,case))

    def test_vector_order_and_no_tail_hardware_write(self):
        for slot in 'ab':
            src=(ROOT/f'foc2_app_{slot}/Core/Src/stm32g4xx_it.c').read_text('utf-8')
            adc=src.split('void ADC1_2_IRQHandler(void)',1)[1].split('void LPUART1_IRQHandler',1)[0]
            self.assertLess(adc.index('ProtectedLoop_PwmEntry'),adc.index('FocAdcTiming_IrqEnter'))
            self.assertLess(adc.index('ProtectedLoop_PwmEntry'),adc.index('ProtectedLoop_AdcIrq'))
            src=(ROOT/f'foc2_app_{slot}/Core/Src/main.c').read_text('utf-8')
            for mode in ('Idle','Speed','Position','Iq'):
                fn=src.split('static void MotorControl_Set'+mode+'(',2)[-1].split('\n}',1)[0]
                self.assertIn('ProtectedLoop_PwmInvalidate',fn)
        duty=(fast.COMMON/'protected_closed_loop.inc').read_text('utf-8').split(
            'static void ProtectedLoop_SetDuty(float du,float dv,float dw)',1)[1]
        branch=duty.split('#elif',1)[0]
        self.assertIn('ProtectedLoop_PwmStage',branch)
        binding=(fast.COMMON/'foc_pwm_pipeline_binding.inc').read_text('utf-8')
        stage=binding.split('static void ProtectedLoop_PwmStage',1)[1]
        self.assertNotRegex(stage,r'TIM1\s*->|PipelineCommit\s*\(')
        adapter=(fast.COMMON/'foc_adc_timing_stm32.c').read_text('utf-8')
        self.assertNotIn('HardOffCommitProbe',adapter)
        commit=adapter.split('int FocAdcTiming_PipelineCommit',1)[1].split('#endif',1)[0]
        self.assertNotRegex(commit,r'->(?:CR1|EGR|SR|CCR4|BDTR|CCER)\s*[|&]?=')

    def test_priority_and_rtos_contract(self):
        for slot in 'ab':
            cfg=(ROOT/f'foc2_app_{slot}/Core/Inc/FreeRTOSConfig.h').read_text('utf-8')
            self.assertRegex(cfg,r'#define configPRIO_BITS\s+4')
            self.assertRegex(cfg,r'#define configLIBRARY_MAX_SYSCALL_INTERRUPT_PRIORITY\s+5')
        src=(fast.COMMON/'protected_closed_loop.inc').read_text('utf-8')
        guard=src.split('void TIM7_DAC_IRQHandler(void)',1)[1].split('#if defined(FOC_FAST_MATH)\n#undef',1)[0]
        self.assertNotRegex(guard,r'\b(?:x\w+FromISR|v\w+FromISR|portYIELD_FROM_ISR)\s*\(')
        header=(fast.COMMON/'foc_preempt_probe.h').read_text('utf-8')
        self.assertIn('#define FOC_SOFTWARE_GUARD_PRIORITY 3U',header)

    def test_build_configuration_hard_off_and_no_power_symbol(self):
        for slot in 'ab':
            b=ROOT/f'foc2_app_{slot}/build/OneCyclePwmPipeline'
            self.assertLessEqual((b/'foc2.bin').stat().st_size,224*1024)
            commands=json.loads((b/'compile_commands.json').read_text('utf-8'))
            cmd=next(x['command'] for x in commands if x['file'].endswith('/Core/Src/main.c'))
            for flag in ('FOC_ONE_CYCLE_PWM_PIPELINE','FOC_FAST_REJECT_COMPUTE_ONLY'):
                self.assertIn('-D'+flag+'=1',cmd)
            symbols=fast.run(fast.ARM/'arm-none-eabi-nm.exe','-S',b/'foc2.elf')
            self.assertIn('ProtectedLoop_PwmEntry',symbols)
            self.assertNotIn(' PowerStage_Enable\n',symbols)
            self.assertNotIn('HardOffCommitProbe',symbols)

    def test_offline_decoder_capture_ownership_and_guard_label(self):
        sys.path.insert(0,str(ROOT/'tools'))
        import pwm_pipeline_report as report
        elf=ROOT/'foc2_app_a/build/OneCyclePwmPipeline/foc2.elf'
        sym=report.base.schema.symbols(elf)
        ram=bytearray(0x20000); flash=bytearray(0x80000)
        image=elf.with_suffix('.bin').read_bytes()
        flash[0x8000:0x8000+len(image)]=image
        def put(name,words):
            addr,size=sym[name]; self.assertEqual(size,4*len(words))
            struct.pack_into('<'+'I'*len(words),ram,addr-0x20000000,*words)
        put('foc_probe_priorities_ok',[1])
        put('foc_probe_irq_priority',[3,1,1,1,2,15,15])
        put('foc_pending_commit_max_cycles',[170])
        p=report.decode(elf,ram,flash,0x08008000)
        self.assertEqual(p['pipeline']['delay_cycles'],1)
        self.assertEqual(p['pipeline']['commit_max_us'],1)
        self.assertFalse(p['irq']['TIM7']['adc_preemption_contributor'])
        self.assertNotIn('exclusive_total_cycles',p['irq']['TIM7'])
        self.assertIn('possible_mixed_latch_count',p['actual_ccr'])
        self.assertFalse(p['actual_ccr']['timer_update_modified_by_probe'])
        self.assertIsNone(p['actual_ccr']['pwm_update_margin_us_min'])
        self.assertIn('NO_VALID_ACTUAL',p['pwm_verdict'])
        with self.assertRaises(ValueError): report.decode(elf,ram,flash,0x08040000)
        flash[0x8100]^=1
        with self.assertRaises(ValueError): report.decode(elf,ram,flash,0x08008000)
        flash[0x8100]^=1
        put('foc_probe_irq_priority',[0,1,1,1,2,15,15])
        with self.assertRaises(ValueError): report.decode(elf,ram,flash,0x08008000)

    def test_pipeline_no_new_compiler_warnings(self):
        for slot in 'ab':
            app=ROOT/f'foc2_app_{slot}'
            dirs={'pipeline':app/'build/OneCyclePwmPipeline',
                  'baseline':app/'build/PipelineReview/FastCurrentRejectComputeOnly'}
            groups={name:json.loads((path/'compile_commands.json').read_text('utf-8'))
                    for name,path in dirs.items()}
            for suffix in ('/Core/Src/main.c','/Core/Src/stm32g4xx_it.c',
                           '/foc_adc_timing_stm32.c','/as5047p_dma_stm32.c'):
                warnings={}
                for name,commands in groups.items():
                    cmd=next(x['command'] for x in commands if x['file'].endswith(suffix))
                    cmd=re.sub(r' -o \S+ -c ',' -fsyntax-only ',cmd)
                    p=subprocess.run(cmd,cwd=dirs[name],capture_output=True,text=True)
                    self.assertEqual(p.returncode,0,p.stderr)
                    warnings[name]=set(re.findall(r'warning: (.*)',p.stderr))
                self.assertFalse(warnings['pipeline']-warnings['baseline'],warnings)
            cmd=next(x['command'] for x in groups['pipeline']
                if x['file'].endswith('/foc_preempt_probe_stm32.c'))
            p=subprocess.run(re.sub(r' -o \S+ -c ',' -fsyntax-only ',cmd),
                             cwd=dirs['pipeline'],capture_output=True,text=True)
            self.assertEqual(p.returncode,0,p.stderr)
            self.assertNotIn('warning:',p.stderr)

if __name__=='__main__': unittest.main()
