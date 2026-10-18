"""Offline FOC-first IRQ/deferred acquisition regressions; no devices."""
import hashlib
import json
import os
import re
import subprocess
import unittest
import test_foc_pwm_pipeline as pipeline
fast=pipeline.fast
ROOT,COMMON=fast.ROOT,fast.COMMON
FLAGS=pipeline.FLAGS+['-DAS5047P_DMA_FOC_FIRST=1']
FROZEN={
    'foc_pwm_pipeline.h':'5405f4560ac540131cec4ea9a11d8a21697fd4735f9c2a19efa7ad108f8500e8',
    'foc_current_fast_reject.h':'a77bf47b2fb3082bf331b0c54782488e253b644cb0f289f4c94b47150288275d',
    'foc_overcurrent_confirm.h':'d3ad09897b0b65aa250c43e474fd05cd7d6499fd260626a45ad2f73617277c92',
}

class EncoderFocFirstTests(unittest.TestCase):
    def test_existing_encoder_protocol_and_transaction_regressions(self):
        fast.OUT.mkdir(exist_ok=True)
        for slot in 'ab':
            for opt in ('-Os','-O2'):
                for stem in ('protocol','transaction','dma_engine'):
                    exe=fast.OUT/f'encoder_existing_{slot}_{stem}_{opt}.exe'
                    sources=[ROOT/f'tests/as5047p_host/{stem}_test.c']
                    if stem=='dma_engine': sources.append(COMMON/'as5047p_dma_engine.c')
                    fast.run(fast.legacy.GCC,'-std=c11',opt,'-Wall','-Wextra','-Werror',
                        '-pedantic','-I',COMMON,'-I',ROOT/f'foc2_app_{slot}/Core/Inc',
                        *sources,'-lm','-o',exe)
                    output=fast.run(exe)
                    self.assertIn('0 failures' if stem=='dma_engine' else 'PASS',output)

    def test_built_candidate_admission_and_warning_delta(self):
        for slot in 'ab':
            root=ROOT/f'foc2_app_{slot}/build'/os.environ.get('FOC_ENCODER_REVIEW_DIR','EncoderReview')
            for suffix,heavy in (('',1),('Light',0)):
                build=root/('EncoderFocFirst'+suffix)
                baseline=root/('OneCyclePwmPipeline'+suffix)
                symbols=fast.run(fast.ARM/'arm-none-eabi-nm.exe','-S',build/'foc2.elf')
                self.assertRegex(symbols,r'\b[Tt] TIM6_DAC_IRQHandler\b')
                self.assertIn(' ProtectedLoop_PwmEntry',symbols)
                self.assertNotIn(' PowerStage_Enable\n',symbols)
                self.assertEqual(' deadline_snapshot\n' in symbols,bool(heavy))
                self.assertLessEqual((build/'foc2.bin').stat().st_size,224*1024)
                groups={p:json.loads((p/'compile_commands.json').read_text('utf-8'))
                        for p in (baseline,build)}
                for source in ('/as5047p_dma_stm32.c','/foc_preempt_probe_stm32.c',
                               '/Core/Src/main.c','/Core/Src/stm32g4xx_it.c'):
                    warnings={}
                    for directory in (baseline,build):
                        command=next(x['command'] for x in groups[directory]
                                     if x['file'].endswith(source))
                        if directory==build:
                            self.assertIn('-DAS5047P_DMA_FOC_FIRST=1',command)
                            self.assertIn(f'-DFOC_HEAVY_PROFILE_ENABLE={heavy}',command)
                        p=subprocess.run(re.sub(r' -o \S+ -c ',' -fsyntax-only ',command),
                            cwd=directory,capture_output=True,text=True)
                        self.assertEqual(p.returncode,0,p.stderr)
                        warnings[directory]=set(re.findall(r'warning: (.*)',p.stderr))
                    self.assertFalse(warnings[build]-warnings[baseline],warnings)

    def test_publication_and_real_deferred_service(self):
        fast.OUT.mkdir(exist_ok=True)
        for opt in ('-Os','-O2'):
            for stem in ('publication','deferred'):
                exe=fast.OUT/f'encoder_{stem}_{opt}.exe'
                sources=[ROOT/f'tests/as5047p_host/{stem}_test.c']
                if stem=='deferred': sources.append(COMMON/'as5047p_dma_engine.c')
                fast.run(fast.legacy.GCC,'-std=c11',opt,'-Wall','-Wextra','-Werror',
                    '-pedantic','-I',COMMON,'-I',ROOT/'foc2_app_a/Core/Inc',*sources,'-o',exe)
                self.assertIn('PASS',fast.run(exe))

    def test_lower_encoder_cannot_pollute_attribution(self):
        for opt in ('-Os','-O2'):
            exe=fast.OUT/f'encoder_attribution_{opt}.exe'
            fast.run(fast.legacy.GCC,'-std=c11',opt,'-Wall','-Wextra','-Werror',
                '-pedantic','-UNDEBUG','-I',ROOT/'tests/foc_preempt_mock','-I',COMMON,*FLAGS,
                COMMON/'foc_preempt_probe_stm32.c',ROOT/'tests/encoder_foc_first_attribution_host.c','-o',exe)
            self.assertIn('PASS lower encoder',fast.run(exe))

    def test_frozen_control_and_pwm_files(self):
        # The opt-in closed-loop adapter deliberately extends three shared
        # sources. Freeze their pre-existing diagnostic BEHAVIOR by rebuilding
        # all old profiles and comparing their BINs in the integration test;
        # never replace historical image hashes with newly generated hashes.
        for name,expected in FROZEN.items():
            data=(COMMON/name).read_bytes()
            self.assertEqual(hashlib.sha256(data).hexdigest(),expected,name)
        for slot in 'ab':
            main=(ROOT/f'foc2_app_{slot}/Core/Src/main.c').read_text('utf-8')
            self.assertIn('sample_age_us > AS_DMA_SAMPLE_MAX_AGE_US',main)
            self.assertIn('theta_e + encoder_omega_e_rad_s * (float)sample_age_us',main)
        header=(COMMON/'as5047p_dma_engine.h').read_text('utf-8')
        for name,value in (('TRANSACTION',200),('GUARD',2),('PERIOD',1000),
                           ('SAMPLE_MAX_AGE',1500),('CONTROL_WATCHDOG',2500)):
            self.assertRegex(header,rf'AS_DMA_{name}_US\s+{value}U')

    def test_actual_health_binding_foc_first_and_priority_drift(self):
        fast.OUT.mkdir(exist_ok=True)
        for opt in ('-Os','-O2'):
            exe=fast.OUT/f'encoder_health_binding_{opt}.exe'
            fast.run(fast.legacy.GCC,'-std=c11',opt,'-Wall','-Wextra','-Werror',
                '-pedantic','-UNDEBUG','-I',COMMON,*FLAGS,
                ROOT/'tests/encoder_health_binding_host.c',
                COMMON/'foc_current_zero.c',COMMON/'foc_zero_median.c',
                COMMON/'foc_zero_robust.c','-o',exe)
            self.assertIn('PASS encoder health',fast.run(exe))

    def test_top_halves_have_no_protocol_math_mask_or_rtos(self):
        src=(COMMON/'as5047p_dma_deferred.inc').read_text('utf-8')
        tops=src.split('FOC_RAM_PATH static void DeferTimerTop')[1].split('FOC_RAM_PATH void TIM6_DAC_IRQHandler')[0]
        self.assertNotRegex(tops,r'\b(?:AsDma_(?:Begin|Guard|RxComplete|Fail)|AS5047P_ParityIsOdd|'
            r'float|double|printf|UART_\w+|__disable_irq|__set_BASEPRI|[xv]\w+FromISR|portYIELD_FROM_ISR)\b')
        self.assertNotRegex(src,r'\b(?:for|while|__disable_irq|__set_BASEPRI|[xv]\w+FromISR|portYIELD_FROM_ISR)\s*\(')
        port=(COMMON/'as5047p_dma_stm32.c').read_text('utf-8')
        get=port.split('int AS5047P_DmaGetSample',1)[1].split('#else',1)[0]
        self.assertNotIn('Lock()',get)
        self.assertIn('AsDma_ReadPublished',get)
        for slot in 'ab':
            cfg=(ROOT/f'foc2_app_{slot}/Core/Inc/FreeRTOSConfig.h').read_text('utf-8')
            self.assertRegex(cfg,r'configLIBRARY_MAX_SYSCALL_INTERRUPT_PRIORITY\s+5')
            presets=json.loads((ROOT/f'foc2_app_{slot}/CMakePresets.json').read_text('utf-8'))
            self.assertTrue(any(p['name']=='EncoderFocFirst' and p['inherits']=='OneCyclePwmPipeline'
                                for p in presets['configurePresets']))


if __name__=='__main__': unittest.main()
