"""Compact all-rejected hard-OFF candidate: actual C / ELF; no board I/O."""
import hashlib
import json
import re
import subprocess
import unittest

import test_foc_irq_compact as compact
import test_foc_zero_all_rejected as zero

ROOT, COMMON, ARM = compact.ROOT, compact.COMMON, compact.ARM
BASE = compact.ram.FLAGS + ['-DFOC_ZERO_ALL_REJECTED_DIAG=1']
FLAGS = BASE + ['-DFOC_IRQ_COMPACT=1']
PRESET = 'ZeroAllRejectedCompact'
PINS = dict(a='9035539aabd09609914e39c13cb5170d18e709efc2ae1269c71accab55ef51e8',
            b='c8637412a9952b57045c1a28a98f38c59287f92d8e197018010974091729dd24')
SOURCES = [COMMON / 'foc_current_zero.c', COMMON / 'foc_zero_median.c',
           COMMON / 'foc_zero_robust.c']


def host(name, source, flags=FLAGS, opt='-O2'):
    return compact.host('all_rejected_' + name, [ROOT / 'tests' / source, *SOURCES], flags, opt=opt)


def blocks(elf):
    asm = compact.run(ARM / 'arm-none-eabi-objdump.exe', '-d', elf)
    return {m[1]: m[2] for m in re.finditer(
        r'^[0-9a-f]+ <([^>]+)>:\n(.*?)(?=^[0-9a-f]+ <|\Z)', asm, re.M | re.S)}


class CompactAllRejectedTests(unittest.TestCase):
    def test_guardian_decisions_unchanged_at_both_optimizations(self):
        for opt in ('-Os', '-O2'):
            ref = host('guard_ref_' + opt, 'foc_compact_guard_host.c', BASE, opt)
            new = host('guard_new_' + opt, 'foc_compact_guard_host.c', FLAGS, opt)
            self.assertEqual(ref, new)
            self.assertIn('PASS 29 guardian cases', new)

    def test_actual_binding_start_denied_and_timeout_off(self):
        for opt in ('-Os', '-O2'):
            self.assertIn('PASS', host('binding_' + opt, 'foc_adaptive_binding_host.c', FLAGS, opt))
        self.assertIn('PASS', host('adc_irq', 'protected_adc_irq_host.c'))

    def test_adaptive_filter_decisions_unchanged(self):
        for opt in ('-Os', '-O2'):
            self.assertEqual(host('filter_ref_' + opt, 'foc_adaptive_equivalence.c', BASE, opt),
                             host('filter_new_' + opt, 'foc_adaptive_equivalence.c', FLAGS, opt))

    def test_zero_full_window_and_all_rejected_results_identical(self):
        # Check the same production estimator with and without compact, not a
        # Python replica. Full-window / 0..4 / all-5 / drift cases also run in
        # the unchanged test_foc_zero_all_rejected suite.
        zero.host.OUT.mkdir(exist_ok=True)
        cases = [([(1560, 1560)] * 4000),
                 ([(1560, 1800), (1560, 1800), (1560, 1560),
                   (1800, 1560), (1800, 1560)] * 800),
                 ([(1560, 1560)] * 100 +
                  [(1400, 1560), (1480, 1400), (1560, 1480), (1640, 1640), (1720, 1720)])]
        for opt in ('-Os', '-O2'):
            exes = []
            for label, flags in (('ref', BASE), ('new', FLAGS)):
                exe = zero.host.OUT / ('compact_zero_' + label + opt + '.exe')
                compact.run(compact.GCC, '-std=c11', opt, '-Wall', '-Wextra', '-Werror',
                    '-pedantic', '-UNDEBUG', '-I', COMMON, *flags,
                    ROOT / 'tests/foc_adaptive_replay.c', *SOURCES, '-o', exe)
                exes.append(exe)
            for values in cases:
                self.assertEqual(zero.adaptive.replay(exes[0], values, '--zero-window'),
                                 zero.adaptive.replay(exes[1], values, '--zero-window'))

    def test_live_adc_clock_and_geometry_faults_retained(self):
        text = compact.host('all_rejected_adc_adapter',
            [ROOT / 'tests/foc_adc_adapter_host.c', COMMON / 'foc_adc_timing_stm32.c',
             COMMON / 'foc_adc_raw_buffer.c', COMMON / 'foc_adc_window.c'],
            FLAGS + ['-DFOC_ADC_SENSE_TOPOLOGY=2'], [ROOT / 'tests/foc_adc_mock'])
        self.assertIn('PASS', text)

    def test_profile_and_old_diagnostic_bins_unchanged(self):
        for slot in 'ab':
            base = ROOT / f'foc2_app_{slot}'
            config = json.loads((base / 'CMakePresets.json').read_text('utf-8'))
            preset = next(p for p in config['configurePresets'] if p['name'] == PRESET)
            self.assertEqual(preset['inherits'], 'ZeroAllRejectedDiagnostic')
            self.assertEqual(preset['cacheVariables'], {'FOC_IRQ_COMPACT': 'ON'})
            self.assertEqual(hashlib.sha256((base / 'build/ZeroAllRejectedDiagnostic/foc2.bin')
                                            .read_bytes()).hexdigest(), PINS[slot])
            data = (base / f'build/{PRESET}/foc2.bin').read_bytes()
            for marker in (b'DIAGNOSTIC=1 HARD_OFF=1 BURST=ALL_REJECTED BLOCK=5 DELTA=40 PAIR=U_OR_V',
                           b'ADAPT=1 HARD_OFF=1 DELAY_PAIRS=1', b'MAX=OFF SEG_MAX=OFF',
                           b'COMPACT ENABLED=1 HARD_OFF=1 FIXED_OPS=1 GUARD_US=25 DEADLINE_US=50'):
                self.assertIn(marker, data)
            cache = (base / f'build/{PRESET}/CMakeCache.txt').read_text('utf-8')
            for name in ('FOC_IRQ_COMPACT', 'FOC_RAM_HOT_PATH', 'FOC_GATE_REUSE',
                         'FOC_ZERO_ALL_REJECTED_DIAG', 'FOC_ADAPTIVE_FILTER_EXPERIMENT'):
                self.assertIn(name + ':BOOL=ON', cache)
            for name in ('FOC_COMPACT_CLOSED_LOOP', 'FOC_LATEST_ORIGINAL_FSM', 'FOC_IRQ_SOURCE_TRACE'):
                self.assertIn(name + ':BOOL=OFF', cache)

    def test_linked_guardian_integer_only_and_fixed_encoder_ops(self):
        for slot in 'ab':
            folder = ROOT / f'foc2_app_{slot}/build/{PRESET}'
            code = blocks(folder / 'foc2.elf')
            syms = compact.run(ARM / 'arm-none-eabi-nm.exe', '-S', folder / 'foc2.elf')
            table = {m[3]: int(m[0], 16) for line in syms.splitlines() if len(m := line.split()) == 4}
            for name in ('ProtectedLoop_AdcIrq', 'TIM7_DAC_IRQHandler', 'TIM2_IRQHandler',
                         'DMA1_Channel4_IRQHandler', 'DMA1_Channel5_IRQHandler',
                         'AsDma_Guard', 'AsDma_Begin', 'FocAdcTiming_FastCanStart'):
                self.assertTrue(0x20000000 <= table[name] < 0x20010000, (slot, name))
            self.assertNotIn('ops', table)
            # These checks now inline into the guardian/ADC; no stale cached
            # health proof is substituted across ticks.
            self.assertNotIn('ProtectedLoop_TimerHealthy', table)
            self.assertNotIn('ProtectedLoop_HealthCaptured', table)
            pending, seen = ['TIM7_DAC_IRQHandler'], set()
            while pending:
                name = pending.pop()
                if name in seen:
                    continue
                seen.add(name)
                body = code[name]
                self.assertFalse(name.endswith('_veneer'), name)
                self.assertNotRegex(body, r'\t(?:v[a-z][a-z0-9]*)(?:\.[a-z0-9]+)?\s', name)
                self.assertNotRegex(body, r'\t(?:blx|bx)\s+r[0-9]+\b', name)
                self.assertNotRegex(body, r'<(?:memcpy|__aeabi_|HAL_Delay|malloc)')
                pending.extend(re.findall(r'\t(?:bl|blx|b(?:\.[wn])?)\s+[^<\n]*<([^+>]+)>', body))
            self.assertIn('ProtectedLoop_EmergencyOff', seen)
            self.assertIn('FocFeedbackGuard_OutputOff', seen)
            mapping = (folder / 'foc2.map').read_text('utf-8')
            end = re.search(r'^\._user_heap_stack\s*\n\s*0x([a-f0-9]+)\s+0x([a-f0-9]+)', mapping, re.M)
            self.assertIsNotNone(end)
            used = sum(int(x, 16) for x in end.groups()) - 0x20000000
            self.assertGreaterEqual(0x1FFC0 - used, 8 * 1024)
            self.assertLessEqual((folder / 'foc2.bin').stat().st_size, 224 * 1024)

    def test_missing_ram_or_control_profile_rejected(self):
        invalid = [[f for f in FLAGS if f != '-DFOC_RAM_HOT_PATH=1'],
                   FLAGS + ['-DFOC_LATEST_ORIGINAL_FSM=1'],
                   FLAGS + ['-DFOC_COMPACT_CLOSED_LOOP=1']]
        for flags in invalid:
            proc = subprocess.run([str(compact.GCC), '-std=c11', '-fsyntax-only', '-I', str(COMMON),
                *flags, str(ROOT / 'tests/foc_adaptive_binding_host.c')], capture_output=True)
            self.assertNotEqual(proc.returncode, 0)


if __name__ == '__main__':
    unittest.main()
