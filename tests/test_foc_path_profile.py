"""Offline-only: profiling, timer geometry, immutable control and linked guards."""
import hashlib
import json
import re
import importlib.util
import subprocess
import unittest
import test_foc_fast_current_reject as fast
import test_foc_rc_protected_candidate as rc


class PathProfileTests(unittest.TestCase):
    def test_actual_stage_stamps(self):
        for opt in ('-Os','-O2'):
            exe=fast.OUT/('profile_stamp'+opt+'.exe')
            fast.run(fast.legacy.GCC,'-std=c11',opt,'-Wall','-Wextra','-Werror','-pedantic',
                '-UNDEBUG','-I',fast.COMMON,'-I',fast.ROOT/'tests/foc_adc_mock',*fast.FLAGS,
                '-DFOC_FAST_REJECT_COMPUTE_ONLY=1','-DFOC_FAST_PATH_PROFILE=1',
                fast.COMMON/'foc_fast_path_profile_stm32.c',
                fast.ROOT/'tests/foc_profile_stamp_host.c','-o',exe)
            self.assertIn('PASS production DWT stamps',fast.run(exe))

    def test_ledger_and_same_bottom_geometry(self):
        fast.OUT.mkdir(exist_ok=True)
        for opt in ('-Os', '-O2'):
            exe=fast.OUT/('path_profile'+opt+'.exe')
            fast.run(fast.legacy.GCC,'-std=c11',opt,'-Wall','-Wextra','-Werror','-pedantic',
                '-UNDEBUG','-I',fast.COMMON,fast.ROOT/'tests/foc_path_profile_host.c','-o',exe)
            self.assertIn('PASS',fast.run(exe))
        # Check the same layout assertions with the MCU ABI, not just host ABI.
        fast.run(fast.ARM/'arm-none-eabi-gcc.exe','-std=c11','-O2','-mcpu=cortex-m4',
            '-mthumb','-mfpu=fpv4-sp-d16','-mfloat-abi=hard','-I',fast.COMMON,
            '-c',fast.ROOT/'tests/foc_path_profile_host.c','-o',fast.OUT/'path_layout_arm.o')

    def test_actual_ccr_adapter(self):
        for opt in ('-Os','-O2'):
            exe=fast.OUT/('profile_adc'+opt+'.exe')
            fast.run(fast.legacy.GCC,'-std=c11',opt,'-Wall','-Wextra','-Werror','-pedantic',
                '-UNDEBUG','-I',fast.COMMON,'-I',fast.ROOT/'tests/foc_adc_mock',
                *rc.ADAPTER_FLAGS,'-DFOC_FAST_PATH_PROFILE=1',
                fast.COMMON/'foc_adc_window.c',fast.COMMON/'foc_adc_raw_buffer.c',
                fast.COMMON/'foc_adc_timing_stm32.c',fast.ROOT/'tests/foc_profile_adc_host.c','-o',exe)
            self.assertIn('PASS actual CCR observer',fast.run(exe))

    def test_protection_and_control_kernels_frozen(self):
        pins={
            'foc_current_fast_reject.h':'a77bf47b2fb3082bf331b0c54782488e253b644cb0f289f4c94b47150288275d',
            'foc_filtered_protection_candidate.h':'fc66017b5d78ccc385e29cb57934b5513ac58f18d228eea3f9078625aeba1e3a',
            'foc_feedback_safety_candidate.h':'d6d3a6b78f5e0a6ea4cd92fb230331c3a9c59754973c603328a707a25b2d4a33',
            'foc_adc_window.c':'49b4b87d8dfeb33c023ff14ec8b3670d1a1e0e751f6e28c2e45ce1d06d2c46c9',
            'foc_fast_trig.c':'dc4341b40f512cb903be3d8f34e57447cd362d0f67b78bc47b3d9b801fc38fa7'}
        for name,digest in pins.items():
            self.assertEqual(hashlib.sha256((fast.COMMON/name).read_bytes()).hexdigest(),digest,name)

    def test_profile_requires_hard_off_and_does_not_log(self):
        for extra in ([],['-DFOC_FAST_CURRENT_REJECT=1'],['-DFOC_FAST_REJECT_COMPUTE_ONLY=1']):
            p=subprocess.run([fast.legacy.GCC,'-std=c11','-fsyntax-only','-x','c',
                '-I',str(fast.COMMON),'-DFOC_FAST_PATH_PROFILE=1',*extra,'-'],
                input='#include "foc_fast_path_profile.h"\n',capture_output=True,text=True)
            self.assertNotEqual(p.returncode,0)
        for name in ('foc_fast_path_profile_stm32.c','foc_pwm_write_probe.h'):
            src=(fast.COMMON/name).read_text('utf-8')
            code=re.sub(r'/\*.*?\*/','',src,flags=re.S)
            self.assertNotRegex(code,r'\b(?:printf|snprintf|UART_\w+|malloc|free|HAL_\w+)\s*\(')

    def test_offline_decoder_distinguishes_unmeasured(self):
        path=fast.ROOT/'tools/foc_path_profile_report.py'
        spec=importlib.util.spec_from_file_location('profile_decoder',path)
        decoder=importlib.util.module_from_spec(spec); spec.loader.exec_module(decoder)
        self.assertIsNone(decoder.pwm([0]*32)['pwm_update_margin_us_min'])
        self.assertIsNone(decoder.phase([0]*42)['normal_total_max_us'])
        words=[0]*32; words[0]=1; words[5]=(-170)&0xffffffff
        self.assertEqual(decoder.pwm(words)['pwm_update_margin_us_min'],-1.0)
        self.assertIsNone(decoder.pwm(words)['ccr_write_max_us'])
        self.assertEqual(decoder.timer_point((100,4200,4,0x101)),
            dict(dwt=100,cnt=4200,observation_span_cycles=4,down=True,valid=True))
        p=subprocess.run(['python',str(path),'--ram','nonexistent.bin'],capture_output=True,text=True)
        self.assertNotEqual(p.returncode,0)
        self.assertIn('must be supplied together',p.stderr)

    def test_previously_qualified_compute_image_is_byte_identical(self):
        build=fast.ROOT/'foc2_app_a/build/FastCurrentRejectComputeOnly'
        self.assertEqual(hashlib.sha256((build/'foc2.bin').read_bytes()).hexdigest(),
            '1cbe43061f7879e5550d0db9301c739c2e00ca213e1ec1a3acb12e3fff5a0bdf')
        self.assertEqual(hashlib.sha256((build/'foc2.elf').read_bytes()).hexdigest(),
            '386a5dea822b590e50d2b75ab1f2c72148883b219223dc11360650470c706fc7')

    def test_linked_diagnostic_is_separate_and_slot_bounded(self):
        for slot in 'ab':
            build=fast.ROOT/f'foc2_app_{slot}/build/FastPathTiming'
            self.assertLessEqual(len((build/'foc2.bin').read_bytes()),224*1024)
            cmds=json.loads((build/'compile_commands.json').read_text('utf-8'))
            main=next(x['command'] for x in cmds if x['file'].endswith('/Core/Src/main.c'))
            self.assertIn('-DFOC_FAST_REJECT_COMPUTE_ONLY=1',main)
            self.assertIn('-DFOC_FAST_PATH_PROFILE=1',main)
            self.assertNotIn('-ffast-math',main)
            symbols=fast.run(fast.ARM/'arm-none-eabi-nm.exe','-S',build/'foc2.elf')
            for name in ('foc_path_profile','foc_pwm_write_profile','foc_pwm_duty_profile',
                         'foc_profile_irq_max','foc_profile_irq_calls'):
                self.assertIn(name,symbols)

    def test_no_new_compile_warnings(self):
        for slot in 'ab':
            app=fast.ROOT/f'foc2_app_{slot}'
            groups={name:json.loads((app/'build'/name/'compile_commands.json').read_text('utf-8'))
                for name in ('FastPathTiming','FastCurrentRejectComputeOnly')}
            for suffix in ('/Core/Src/main.c','/foc_adc_timing_stm32.c','/as5047p_dma_stm32.c'):
                warnings={}
                for profile,commands in groups.items():
                    command=next(x['command'] for x in commands if x['file'].endswith(suffix))
                    command=re.sub(r' -o \S+ -c ',' -fsyntax-only ',command)
                    p=subprocess.run(command,cwd=app/'build'/profile,capture_output=True,text=True)
                    self.assertEqual(p.returncode,0,p.stderr)
                    warnings[profile]=set(re.findall(r'warning: (.*)',p.stderr))
                self.assertFalse(warnings['FastPathTiming']-warnings['FastCurrentRejectComputeOnly'])

if __name__=='__main__': unittest.main()
