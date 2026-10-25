"""Offline RC protected integration; no device, private data or motion I/O."""

from app_source_view import read_app_source
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest

import test_foc_startup_evidence as startup

ROOT = Path(__file__).resolve().parents[1]
COMMON = ROOT / 'firmware_common'
OUT = ROOT / 'tests/foc_adc_window_build'
GCC = startup.latest.GCC
RC = 'FOC_ADC_RC_PROTECTED_CANDIDATE=1'
FLAGS = startup.FLAGS + ['-D' + RC]
ADAPTER_FLAGS = FLAGS + ['-DFOC_ADC_RC_MIN_LOW_ON_TICKS=1700']


def run(*args):
    p = subprocess.run([str(a) for a in args], capture_output=True, text=True, timeout=45)
    if p.returncode:
        raise AssertionError(p.stdout + p.stderr)
    return p.stdout


class RcProtectedTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        OUT.mkdir(exist_ok=True)

    def test_real_adapter_deadline_and_no_write_rejection_cases(self):
        for opt in ('-Os', '-O2'):
            exe = OUT / ('rc_commit' + opt + '.exe')
            run(GCC, '-std=c11', opt, '-Wall', '-Wextra', '-Werror', '-pedantic', '-UNDEBUG',
                '-I', COMMON, '-I', ROOT / 'tests/foc_adc_mock', *ADAPTER_FLAGS,
                COMMON / 'foc_adc_window.c', COMMON / 'foc_adc_raw_buffer.c',
                COMMON / 'foc_adc_timing_stm32.c', ROOT / 'tests/foc_rc_commit_host.c', '-o', exe)
            for case in range(14):
                with self.subTest(opt=opt, case=case):
                    self.assertIn('PASS', run(exe, case))

    def test_actual_original_fsm_binding_admission_and_fault_races(self):
        for opt in ('-Os', '-O2'):
            exe = OUT / ('rc_binding' + opt + '.exe')
            run(GCC, '-std=c11', opt, '-Wall', '-Wextra', '-Werror', '-pedantic', '-UNDEBUG',
                '-I', COMMON, *FLAGS, ROOT / 'tests/foc_rc_protected_binding_host.c',
                COMMON / 'foc_current_zero.c', COMMON / 'foc_zero_median.c',
                COMMON / 'foc_zero_robust.c', '-o', exe)
            self.assertIn('PASS', run(exe))

    def test_direct_header_rejects_partial_or_bypass_configurations(self):
        required = ['FOC_PROTECTED_CLOSED_LOOP', 'FOC_LATEST_ORIGINAL_FSM', 'FOC_STARTUP_TRACE',
                    'FOC_IRQ_COMPACT', 'FOC_GATE_REUSE', 'FOC_ADC_WINDOW']
        base = [RC, 'FOC_ADC_SENSE_TOPOLOGY=2', *[key + '=1' for key in required]]
        def compile(defines):
            return subprocess.run([GCC, '-std=c11', '-fsyntax-only', '-x', 'c', '-I', str(COMMON),
                *['-D' + value for value in defines], '-'],
                input='#include "foc_adc_timing_stm32.h"\n', capture_output=True, text=True)
        self.assertEqual(compile(base).returncode, 0)
        rejected = [[value for value in base if value != key + '=1'] for key in required]
        rejected += [base + [key + '=1'] for key in ('FOC_ADC_RC_DIAGNOSTIC',
                       'FOC_ADAPTIVE_FILTER_EXPERIMENT', 'FOC_COMPACT_CLOSED_LOOP')]
        rejected += [base + ['FOC_ADC_RC_MIN_LOW_ON_TICKS=' + value] for value in ('1699', '4250')]
        rejected.append([value for value in base if value != 'FOC_ADC_SENSE_TOPOLOGY=2'])
        for flags in rejected:
            with self.subTest(flags=flags):
                result = compile(flags)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('RC', result.stderr)

    def test_new_profile_separate_and_previous_images_not_overwritten(self):
        pins = {
            'a': {'RcSamplingComputeOnly': '951a9381cd18e5614b685d8ca978e466d0746252a03c3554892595c549a0ccf3'},
            'b': {'RcSamplingComputeOnly': 'deadaa1290a530676ddbdc27799a57e48ee72fde381682dbdf63d90e4d410119',
                  'LatestOriginalStartupEvidence': '2450f5a6da36c0698690aa2353fd1f76758e4b7401453fb7f361cfab1e72c61b'}}
        for slot in 'ab':
            app = ROOT / f'foc2_app_{slot}'
            presets = {p['name']: p for p in json.loads((app/'CMakePresets.json').read_text('utf-8'))['configurePresets']}
            new = presets['RcSamplingProtectedCandidate']
            self.assertEqual(new['inherits'], 'LatestOriginalStartupEvidence')
            self.assertEqual(new['cacheVariables']['FOC_ADC_RC_PROTECTED_CANDIDATE'], 'ON')
            for name, sha in pins[slot].items():
                self.assertEqual(hashlib.sha256((app/f'build/{name}/foc2.bin').read_bytes()).hexdigest(), sha)
            source = read_app_source(app/'Core/Src/main.c','utf-8')
            self.assertIn('strcmp(cmd, "ADC COMMIT") == 0', source)

    def test_linked_candidate_keeps_protection_and_original_start(self):
        for slot in 'ab':
            folder = ROOT / f'foc2_app_{slot}/build/RcSamplingProtectedCandidate'
            image = (folder/'foc2.bin').read_bytes()
            for marker in (b'NAME=RC_PROTECTED_CANDIDATE HARD_OFF=0 ADAPT=1 FSM=ORIGINAL',
                           b'ADAPT=1 HARD_OFF=0 DELAY_PAIRS=1', b'USE_ORIGINAL_START',
                           b'FILTER=TREND4 OC=2_OF_3 TRIP_MA=4000',
                           b'RAM ENABLED=1 HARD_OFF=0 DEADLINE_US=50',
                           b'STARTUP CONFIG ENABLED=1 ROWS=32 FIRST_CAUSE=1',
                           b'OK ADC COMMIT RC=%u READY=%u CHECK=%lu FAIL=%lu BOTTOM_LATE=%lu'):
                self.assertIn(marker, image)
            self.assertLessEqual(len(image), 224 * 1024)
            rows = json.loads((folder/'compile_commands.json').read_text('utf-8'))
            command = next(row['command'] for row in rows
                           if row['file'].replace('\\','/').endswith('/Core/Src/main.c'))
            self.assertIn('-DFOC_ADC_RC_PROTECTED_CANDIDATE=1', command)
            self.assertIn('-DFOC_STARTUP_TRACE=1', command)
            for forbidden in ('-DFOC_ADAPTIVE_FILTER_EXPERIMENT=1', '-DFOC_ADC_RC_DIAGNOSTIC=1',
                              '-DFOC_RAW_OBSERVE_ONLY=1', '-DFOC_FILTERED_OBSERVE_ONLY=1'):
                self.assertNotIn(forbidden, command)

    def test_linked_deadline_checks_and_emergency_closure_are_reachable(self):
        arm = Path(r'D:\software\arm\bin')
        for slot in 'ab':
            elf = ROOT / f'foc2_app_{slot}/build/RcSamplingProtectedCandidate/foc2.elf'
            symbols = run(arm/'arm-none-eabi-nm.exe', '-S', '-n', elf)
            for name in ('FocAdcTiming_RcActuationReady', 'FocAdcTiming_CommitBeforeBottom',
                         'ProtectedLoop_AdcIrq', 'ProtectedLoop_EmergencyOff',
                         'TIM7_DAC_IRQHandler'):
                match = re.search(r'^([0-9a-f]+) [0-9a-f]+ [Tt] ' + name + r'$', symbols, re.M)
                self.assertIsNotNone(match, name)
                self.assertTrue(0x20000000 <= int(match[1], 16) < 0x20010000, name)
            disassembly = run(arm/'arm-none-eabi-objdump.exe', '-d', elf)
            irq = disassembly.split('<ProtectedLoop_AdcIrq>:', 1)[1].split('\n\n', 1)[0]
            duty = disassembly.split('<ProtectedLoop_SetDuty>:', 1)[1].split('\n\n', 1)[0]
            self.assertIn('<ProtectedLoop_SetDuty>', irq)
            self.assertIn('<FocAdcTiming_CommitBeforeBottom>', duty)
            self.assertIn('<ProtectedLoop_EmergencyOff>', duty)
            # Thread-mode START still calls admission, rather than a new motor entry.
            self.assertRegex(disassembly, r'bl\s+[^\n]*<[^\n]*FocAdcTiming_RcActuationReady')

    def test_cmake_rejects_mixed_diagnostic_missing_trace_and_short_rc_budget(self):
        environment = os.environ.copy()
        environment['PATH'] = r'D:\software\arm\bin;D:\software\ninja;' + environment['PATH']
        cases = ('-DFOC_ADC_RC_DIAGNOSTIC=ON', '-DFOC_STARTUP_TRACE=OFF',
                 '-DFOC_ADC_RC_MIN_LOW_ON_TICKS=1699')
        for slot in 'ab':
            for flag in cases:
                with self.subTest(slot=slot, flag=flag), tempfile.TemporaryDirectory(prefix='foc-rc-gate-') as folder:
                    result = subprocess.run([r'C:\Program Files\CMake\bin\cmake.exe',
                        '--preset', 'RcSamplingProtectedCandidate', '-B', folder, flag],
                        cwd=ROOT/f'foc2_app_{slot}', env=environment,
                        capture_output=True, text=True, timeout=45)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn('RC', result.stdout + result.stderr)
                    self.assertIn('CMake Error', result.stdout + result.stderr)


if __name__ == '__main__':
    unittest.main()
