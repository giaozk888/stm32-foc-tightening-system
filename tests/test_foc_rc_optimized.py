"""Offline only: no device access or changes to measured predecessor images."""
import hashlib
import json
from pathlib import Path
import re
import unittest
import test_foc_rc_protected_candidate as rc

ROOT = Path(__file__).resolve().parents[1]


class RcOptimizedTests(unittest.TestCase):
    def test_planner_matches_preoptimization_reference(self):
        rc.OUT.mkdir(exist_ok=True)
        for opt in ('-Os', '-O2'):
            exe = rc.OUT / ('rc_equivalence' + opt + '.exe')
            rc.run(rc.GCC, '-std=c11', opt, '-Wall', '-Wextra', '-Werror',
                   '-pedantic', '-UNDEBUG', '-I', rc.COMMON,
                   rc.COMMON/'foc_adc_window.c',
                   ROOT/'tests/foc_adc_window_reference.c',
                   ROOT/'tests/foc_adc_window_equivalence_host.c', '-o', exe)
            self.assertIn('PASS 1319107 full-plan equivalence cases', rc.run(exe))

    def test_ready_skip_and_stop_fault_races(self):
        # Executes the actual shared binding, including the early rejection
        # counter assertions and the post-planning guard/STOP races.
        rc.OUT.mkdir(exist_ok=True)
        for opt in ('-Os', '-O2'):
            exe = rc.OUT / ('rc_optimized_binding' + opt + '.exe')
            rc.run(rc.GCC, '-std=c11', opt, '-Wall', '-Wextra', '-Werror',
                   '-pedantic', '-UNDEBUG', '-I', rc.COMMON, *rc.FLAGS,
                   ROOT/'tests/foc_rc_protected_binding_host.c',
                   rc.COMMON/'foc_current_zero.c', rc.COMMON/'foc_zero_median.c',
                   rc.COMMON/'foc_zero_robust.c', '-o', exe)
            self.assertIn('PASS', rc.run(exe))

    def test_new_directory_and_measured_predecessors_preserved(self):
        hashes = {'a': 'ff7660fb65aef3527a3d5c81a71d11d6a13e440facd90704dfb6c3fea366fb7c',
                  'b': '61abcdc9ee6c92a34c4920562e8a3e6e9ac6404653e56b7466020f4257b752df'}
        for slot in 'ab':
            app = ROOT/f'foc2_app_{slot}'
            presets = json.loads((app/'CMakePresets.json').read_text('utf-8'))
            new = next(p for p in presets['configurePresets']
                       if p['name'] == 'RcSamplingOptimizedCandidate')
            self.assertEqual(new['inherits'], 'RcSamplingProtectedCandidate')
            self.assertNotIn('cacheVariables', new)
            self.assertEqual(hashlib.sha256((app/'build/RcSamplingProtectedCandidate/foc2.bin').read_bytes()).hexdigest(), hashes[slot])

    def test_linked_new_images_keep_checks_and_ram_transaction(self):
        arm = Path(r'D:\software\arm\bin')
        for slot in 'ab':
            build = ROOT/f'foc2_app_{slot}/build/RcSamplingOptimizedCandidate'
            image = (build/'foc2.bin').read_bytes()
            for marker in (b'FILTER=TREND4 OC=2_OF_3 TRIP_MA=4000',
                           b'RAM ENABLED=1 HARD_OFF=0 DEADLINE_US=50',
                           b'FSM=ORIGINAL', b'LEASE_US=400000', b'HW_VERIFIED=0'):
                self.assertIn(marker, image)
            symbols = rc.run(arm/'arm-none-eabi-nm.exe', '-S', '-n', build/'foc2.elf')
            for name in ('FocAdcWindow_Plan', 'FocAdcWindow_Duty',
                         'FocAdcTiming_Prepare', 'FocAdcTiming_CommitPrepared',
                         'FocAdcTiming_CommitBeforeBottom', 'ProtectedLoop_SetDuty',
                         'ProtectedLoop_EmergencyOff', 'TIM7_DAC_IRQHandler'):
                match = re.search(r'^([0-9a-f]+) [0-9a-f]+ [Tt] '+name+r'$', symbols, re.M)
                self.assertIsNotNone(match, name)
                self.assertTrue(0x20000000 <= int(match[1],16) < 0x20010000, name)
            self.assertLessEqual(len(image), 224*1024)


if __name__ == '__main__':
    unittest.main()
