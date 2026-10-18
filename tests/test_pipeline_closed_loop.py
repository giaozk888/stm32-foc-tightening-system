"""Candidate integration, mocks and files ONLY. Never imports a device runner."""
import json
import re
import subprocess
import unittest
import test_foc_preempt_commit_probe as pre
import test_foc_rc_protected_candidate as rc

fast=pre.fast
ROOT=fast.ROOT
FLAGS=list(dict.fromkeys(fast.FLAGS+rc.ADAPTER_FLAGS+[
    '-DFOC_PWM_PIPELINE_CLOSED_LOOP=1','-DFOC_ONE_CYCLE_PWM_PIPELINE=1',
    '-DFOC_PREEMPT_COMMIT_PROBE=1','-DAS5047P_DMA_FOC_FIRST=1']))

class PipelineClosedLoopTests(unittest.TestCase):
    def test_protected_original_fsm_and_pipeline(self):
        for opt in ('-Os','-O2'):
            for heavy in (0,1):
                exe=fast.OUT/f'pipeline_closed_loop_{opt}_{heavy}.exe'
                fast.run(fast.legacy.GCC,'-std=c11',opt,'-Wall','-Wextra','-Werror','-pedantic',
                    '-UNDEBUG','-I',fast.COMMON,*FLAGS,f'-DFOC_HEAVY_PROFILE_ENABLE={heavy}',
                    ROOT/'tests/foc_pipeline_closed_loop_host.c',
                    fast.COMMON/'foc_current_zero.c',fast.COMMON/'foc_zero_median.c',
                    fast.COMMON/'foc_zero_robust.c','-o',exe)
                for case in range(20):
                    with self.subTest(opt=opt,heavy=heavy,case=case):
                        self.assertIn('PASS protected pipeline',fast.run(exe,case))

    def test_real_commit_adapter_both_profile_modes(self):
        for opt in ('-Os','-O2'):
            for heavy in (0,1):
                exe=fast.OUT/f'pipeline_power_commit_{opt}_{heavy}.exe'
                fast.run(fast.legacy.GCC,'-std=c11',opt,'-Wall','-Wextra','-Werror','-pedantic',
                    '-UNDEBUG','-I',ROOT/'tests/foc_preempt_mock','-I',fast.COMMON,
                    *FLAGS,f'-DFOC_HEAVY_PROFILE_ENABLE={heavy}',fast.COMMON/'foc_adc_window.c',
                    fast.COMMON/'foc_adc_raw_buffer.c',fast.COMMON/'foc_adc_timing_stm32.c',
                    ROOT/'tests/foc_pipeline_power_commit_host.c','-o',exe)
                for case in range(10):
                    with self.subTest(opt=opt,heavy=heavy,case=case):
                        self.assertIn('PASS actuating CCR',fast.run(exe,case))

    def test_mixed_or_partial_configuration_rejected(self):
        for extra in ('FOC_FAST_REJECT_COMPUTE_ONLY=1','FOC_ENABLE_LEGACY_CURRENT_REPAIR=1',
                      'FOC_FAST_PATH_PROFILE=1','FOC_RC_DEFERRED_SHADOW=1'):
            p=subprocess.run([fast.legacy.GCC,'-std=c11','-fsyntax-only','-x','c',
                '-I',str(fast.COMMON),*FLAGS,'-D'+extra,'-'],
                input='#include "foc_preempt_probe.h"\n',capture_output=True,text=True)
            self.assertNotEqual(p.returncode,0,extra)
        for drop in ('FOC_ONE_CYCLE_PWM_PIPELINE','AS5047P_DMA_FOC_FIRST','FOC_LATEST_ORIGINAL_FSM'):
            p=subprocess.run([fast.legacy.GCC,'-std=c11','-fsyntax-only','-x','c',
                '-I',str(fast.COMMON),*[f for f in FLAGS if f!='-D'+drop+'=1'],'-'],
                input='#include "foc_preempt_probe.h"\n',capture_output=True,text=True)
            self.assertNotEqual(p.returncode,0,drop)

    def test_candidate_build_contract(self):
        for slot in 'ab':
            b=ROOT/f'foc2_app_{slot}/build/ClosedLoopIntegration/ProtectedPipelineClosedLoop'
            self.assertLessEqual((b/'foc2.bin').stat().st_size,224*1024)
            commands=json.loads((b/'compile_commands.json').read_text('utf-8'))
            cmd=next(x['command'] for x in commands if x['file'].endswith('/Core/Src/main.c'))
            for flag in ('FOC_PWM_PIPELINE_CLOSED_LOOP=1','AS5047P_DMA_FOC_FIRST=1',
                         'FOC_ONE_CYCLE_PWM_PIPELINE=1','FOC_HEAVY_PROFILE_ENABLE=0',
                         'FOC_LATEST_ORIGINAL_FSM=1','FOC_FAST_CURRENT_REJECT=1'):
                self.assertIn('-D'+flag,cmd)
            self.assertNotIn('-DFOC_FAST_REJECT_COMPUTE_ONLY=1',cmd)

    def test_no_new_source_warnings(self):
        for slot in 'ab':
            root=ROOT/f'foc2_app_{slot}/build/ClosedLoopIntegration'
            groups={}
            for profile in ('EncoderFocFirstLight','ProtectedPipelineClosedLoop'):
                groups[profile]=json.loads((root/profile/'compile_commands.json').read_text('utf-8'))
            for source in ('/Core/Src/main.c','/Core/Src/stm32g4xx_it.c',
                           '/as5047p_dma_stm32.c','/foc_adc_timing_stm32.c','/foc_preempt_probe_stm32.c'):
                warnings={}
                for profile,commands in groups.items():
                    cmd=next(x['command'] for x in commands if x['file'].endswith(source))
                    p=subprocess.run(re.sub(r' -o \S+ -c ',' -fsyntax-only ',cmd),
                        cwd=root/profile,capture_output=True,text=True)
                    self.assertEqual(p.returncode,0,p.stderr)
                    warnings[profile]=set(re.findall(r'warning: (.*)',p.stderr))
                self.assertFalse(warnings['ProtectedPipelineClosedLoop']-warnings['EncoderFocFirstLight'],warnings)

    def test_historical_profiles_bit_identical(self):
        import hashlib
        receipt=json.loads((ROOT/'tests/foc_adaptive_build/encoder_health_evidence/receipt.json').read_text('utf-8'))
        for row in receipt['builds']:
            if not row['bin_sha256']: continue
            image=ROOT/row['app']/'build/ClosedLoopIntegration'/row['profile']/'foc2.bin'
            self.assertEqual(hashlib.sha256(image.read_bytes()).hexdigest(),row['bin_sha256'],
                             (row['app'],row['profile']))

if __name__=='__main__': unittest.main()
