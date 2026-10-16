"""Offline proof that the deferred candidate is an output-locked observer."""
import hashlib
import json
from pathlib import Path
import re
import subprocess
import unittest

import test_foc_rc_protected_candidate as rc

ROOT = rc.ROOT
COMMON = ROOT/'firmware_common'
PINS = {
    'a': '0990cdf2ec7fde9c169afdc3d67cb2d3ea772ae29fd90b0c9b4f565565f05e20',
    'b': '9fd54166df782cce3e737ecfebe67bc4aff8f15a005fca1f1136c91bb8786f44',
}


class DeferredShadowTests(unittest.TestCase):
    def test_profile_requires_locked_original_rc_chain(self):
        flags = rc.ADAPTER_FLAGS + ['-DFOC_PWM_BOUNDARY_LITE=1',
                                    '-DFOC_RC_DEFERRED_SHADOW=1']
        for extra in (['-UFOC_PWM_BOUNDARY_LITE'], ['-UFOC_LATEST_ORIGINAL_FSM'],
                      ['-UFOC_ADC_RC_PROTECTED_CANDIDATE'],
                      ['-DFOC_ADAPTIVE_FILTER_EXPERIMENT=1']):
            p = subprocess.run([str(rc.GCC), '-std=c11', '-fsyntax-only', '-x', 'c',
                '-I', str(COMMON), *flags, *extra, '-'],
                input='#include "foc_hot_path.h"\n', capture_output=True, text=True)
            self.assertNotEqual(p.returncode, 0, extra)

    def test_bridge_admission_compiled_out_at_both_call_sites(self):
        source = (COMMON/'protected_closed_loop.inc').read_text('utf-8')
        original = (COMMON/'latest_original_fsm.inc').read_text('utf-8')
        self.assertRegex(source, r'FOC_ADAPTIVE_FILTER_EXPERIMENT\) \|\| '
                                 r'defined\(FOC_RC_DEFERRED_SHADOW\)\n'
                                 r'\s*return 0U;')
        self.assertIn('#if defined(FOC_RC_DEFERRED_SHADOW)\n'
                      '    /* This observer must have no compiled bridge-enable transaction. */\n'
                      '    return 0U;', original)
        duty = source.split('static void ProtectedLoop_SetDuty(', 1)[1]
        shadow = duty.split('#elif defined(FOC_ADAPTIVE_FILTER_EXPERIMENT)', 1)[0]
        self.assertNotIn('CommitPrepared(', shadow)
        self.assertNotIn('CommitBeforeBottom(', shadow)
        self.assertNotIn('TIM1->CCER=0x555U', shadow)
        self.assertIn('FocRcDeferredPlan_Stage(', shadow)
        probe = source.split('static void ProtectedLoop_DeferredProbe(', 1)[1]
        probe = probe.split('/* Actual 1 kHz task', 1)[0]
        self.assertIn('FocRcDeferredPlan_Take(', probe)
        self.assertIn('(void)plan;', probe)
        self.assertNotIn('CommitPrepared(', probe)

    def test_both_linked_images_locked_and_prior_pins_unchanged(self):
        objdump = Path(r'D:\software\arm\bin\arm-none-eabi-objdump.exe')
        for slot in 'ab':
            app = ROOT/f'foc2_app_{slot}'
            presets = json.loads((app/'CMakePresets.json').read_text('utf-8'))
            p = next(p for p in presets['configurePresets'] if p['name']=='RcDeferredShadow')
            self.assertEqual(p['inherits'], 'RcBoundaryLite')
            pin = app/'build/RcSamplingOptimizedCandidate/foc2.bin'
            self.assertEqual(hashlib.sha256(pin.read_bytes()).hexdigest(), PINS[slot])
            build = app/'build/RcDeferredShadow'
            image = (build/'foc2.bin').read_bytes()
            self.assertIn(b'NAME=RC_DEFERRED_SHADOW HARD_OFF=0 ADMISSION=0', image)
            self.assertIn(b'MOTOR TEST DEFERRED', image)
            self.assertLessEqual(len(image), 224*1024)
            asm = rc.run(objdump, '-d', build/'foc2.elf')
            for name in ('FocAdcTiming_RcActuationReady',
                         'FocAdcTiming_CommitBeforeBottom'):
                body = asm.split('<'+name+'>:', 1)[1].split('\n\n', 1)[0]
                self.assertRegex(body, r'movs\s+r0, #0')


if __name__ == '__main__':
    unittest.main()
