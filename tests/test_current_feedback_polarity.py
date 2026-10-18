"""Offline only. No serial, debugger, flash, reset or motor imports."""
import subprocess
import unittest
import test_foc_fast_current_reject as fast

ROOT=fast.ROOT
OUT=ROOT/'tests/current_polarity_build'

class CurrentPolarityTests(unittest.TestCase):
    def test_feedback_and_protection_both_signs(self):
        OUT.mkdir(exist_ok=True)
        for sign in (-1,1):
            for opt in ('-Os','-O2'):
                exe=OUT/f'polarity_{sign}_{opt}.exe'
                fast.run(fast.legacy.GCC,'-std=c11',opt,'-Wall','-Wextra','-Werror',
                    '-pedantic','-UNDEBUG','-I',fast.COMMON,*fast.FLAGS,
                    '-DFOC_FAST_REJECT_COMPUTE_ONLY=1',f'-DFOC_CURRENT_FEEDBACK_SIGN={sign}',
                    ROOT/'tests/foc_current_polarity_host.c','-o',exe)
                self.assertIn('PASS current polarity',fast.run(exe))

    def test_invalid_or_actuating_reverse_sign_rejected(self):
        for defs in (['-DFOC_CURRENT_FEEDBACK_SIGN=0'],
                     ['-DFOC_CURRENT_FEEDBACK_SIGN=2'],
                     ['-DFOC_CURRENT_FEEDBACK_SIGN=1'],
                     ['-DFOC_CURRENT_FEEDBACK_SIGN=1','-DFOC_FAST_REJECT_COMPUTE_ONLY=0']):
            p=subprocess.run([fast.legacy.GCC,'-std=c11','-fsyntax-only','-x','c',
                '-I',str(fast.COMMON),*defs,'-'],
                input='#include "foc_current_feedback_polarity.h"\n',
                capture_output=True,text=True)
            self.assertNotEqual(p.returncode,0,defs)

    def test_default_kernel_matches_legacy_machine_code(self):
        OUT.mkdir(exist_ok=True)
        bodies={
            'legacy':'return ((int32_t)zero-(int32_t)raw)*scale;',
            'default':'return FocCurrentFeedback_FromRaw(raw,zero,scale);'}
        blobs={}
        for name,body in bodies.items():
            obj=OUT/f'{name}.o'
            source=('#include "foc_current_feedback_polarity.h"\n'
                    'float sample(uint16_t raw,uint16_t zero,float scale){'+body+'}\n')
            p=subprocess.run([str(fast.ARM/'arm-none-eabi-gcc.exe'),'-std=c11',
                '-O2','-mcpu=cortex-m4','-mthumb','-mfpu=fpv4-sp-d16',
                '-mfloat-abi=hard','-I',str(fast.COMMON),'-x','c','-c','-',
                '-o',str(obj)],input=source,capture_output=True,text=True)
            self.assertEqual(p.returncode,0,p.stderr)
            binary=OUT/f'{name}.bin'
            fast.run(fast.ARM/'arm-none-eabi-objcopy.exe','-O','binary',
                '--only-section=.text',obj,binary)
            blobs[name]=binary.read_bytes()
        self.assertTrue(blobs['legacy'])
        self.assertEqual(blobs['legacy'],blobs['default'])

if __name__=='__main__': unittest.main()
