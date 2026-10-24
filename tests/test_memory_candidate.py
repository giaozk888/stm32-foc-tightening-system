"""Files-only acceptance for A footprint profiles; no device access."""
import hashlib
import json
from pathlib import Path
import re
import subprocess
import unittest

from test_torque_chain import GCC, FROZEN, function
from test_torque350_five_second import expanded

ROOT = Path(__file__).resolve().parents[1]
ARM = Path('D:/software/arm/bin')
PAIRS = (('BemfFittedFluxCandidate', 'BemfFittedMemoryCandidate'),
         ('KaSynchronizedDiagnostic', 'KaSynchronizedMemoryDiagnostic'))


def directory(preset):
    return ROOT / 'foc2_app_a/build' / preset


def symbols(preset):
    return subprocess.run([str(ARM/'arm-none-eabi-nm.exe'), '-S',
        str(directory(preset)/'foc2.elf')], capture_output=True, text=True, check=True).stdout


class MemoryCandidateTests(unittest.TestCase):
    def test_linker_region_savings_and_warning_set(self):
        for old, new in PAIRS:
            usage = []
            warnings = []
            for preset in (old, new):
                output = subprocess.run([str(ARM/'arm-none-eabi-size.exe'), '-A',
                    str(directory(preset)/'foc2.elf')], capture_output=True, text=True, check=True).stdout
                sizes = dict((name, int(size)) for name, size in
                             re.findall(r'(?m)^(\.[\w.]+)\s+(\d+)\s+\d+', output))
                usage.append(sum(sizes[n] for n in ('.data', '.bss', '._user_heap_stack')))
                command = next(c['command'] for c in json.loads(
                    (directory(preset)/'compile_commands.json').read_text())
                    if c['file'].endswith('/Core/Src/main.c'))
                check = subprocess.run(re.sub(r' -o \S+ -c ', ' -fsyntax-only ', command),
                    cwd=directory(preset), capture_output=True, text=True, check=True)
                warnings.append(set(re.findall(r'warning: ([^\n]+)', check.stderr)))
            self.assertEqual(usage[0] - usage[1], 5536)
            self.assertGreaterEqual(131008 - usage[1], 5656)
            self.assertEqual(warnings[0], warnings[1])

    def test_space_saved_and_only_generic_test_registration_removed(self):
        for old, new in PAIRS:
            before, after = symbols(old), symbols(new)
            self.assertIn('PW_UnitTestsRun', before)
            self.assertNotIn('PW_UnitTestsRun', after)
            self.assertNotIn('_ZN2pw9unit_test8internal9Framework10framework_E', after)
            self.assertRegex(before, r'00003400 [bB] s_slots')
            self.assertRegex(after, r'00002700 [bB] s_slots')
            # Stacks/heap and raw/startup capture are not used as a savings lever.
            for name in ('ucHeap', 's_task_stack', 'statistics_stack', 'cl_startup', 'raw_buffers'):
                rx = r'(?m)^\S+ (\S+) [a-zA-Z] ' + name + '$'
                self.assertEqual(re.search(rx, before)[1], re.search(rx, after)[1], name)
            self.assertEqual(re.search(r'(?m)^\S+ (\S+) [a-zA-Z] ucHeap$', after)[1], '0000a000')
            self.assertLess((directory(new)/'foc2.bin').stat().st_size,
                            (directory(old)/'foc2.bin').stat().st_size - 6000)
            for name in ('PW_Allocator_RunSelfTest', 'PW_SmokeTest', 'PW_ThreadSmokeStart'):
                self.assertIn(name, after)

    def test_control_safety_protocol_and_startup_except_generic_tests_identical(self):
        names = FROZEN + ('TighteningTask', 'MotorControlTask', 'FOC_ResetController',
            'Encoder_ElectricalAngleRad', 'MotorControl_SetSpeed', 'MotorControl_SetIq',
            'ProtectedLoop_Ready', 'ProtectedLoop_Command', 'Protocol_HandleLine',
            'Protocol_PrintStatus', 'PowerStage_Disable', 'MonitorTask')
        for old, new in PAIRS:
            before, after = expanded('a', old), expanded('a', new)
            for name in names:
                self.assertEqual(function(before, name), function(after, name), (new, name))
            a = function(before, 'StartupTask').replace('PW_UnitTestsRun();', '')
            b = function(after, 'StartupTask')
            self.assertEqual(re.sub(r'\s+', '', a), re.sub(r'\s+', '', b))

    def test_realtime_objects_byte_identical(self):
        for old, new in PAIRS:
            for obj in ('stm32g4xx_it.c.obj', 'foc_adc_timing_stm32.c.obj',
                        'as5047p_dma_stm32.c.obj', 'foc_fast_trig.c.obj',
                        'foc_zero_robust.c.obj', 'tightening_intent_fsm.c.obj'):
                a, b = [next(directory(p).rglob(obj)).read_bytes() for p in (old, new)]
                self.assertEqual(a, b, (new, obj))

    def test_old_images_and_b_not_replaced(self):
        paths = {
            'foc2_app_a/build/BemfFittedFluxCandidate/foc2.bin':
                '6e66984d9867de2f25b362c14b6549eec2043406905f031bdf12c1594cbaad3f',
            'foc2_app_a/build/KaSynchronizedDiagnostic/foc2.bin':
                '5428b7993a5bc8f8f7ce22772d29efb800c1244699df546231d33ec825c0c136',
            'foc2_app_b/build/AccelFfBUnchanged/foc2.bin':
                '7ebdb56408baaa6c213c5dabe236250be673ed5a5c1345dfe64861d1e98dd366'}
        for path, sha in paths.items():
            self.assertEqual(hashlib.sha256((ROOT/path).read_bytes()).hexdigest(), sha)

    def test_default_legacy_and_new_profiles_explicit(self):
        presets = {p['name']: p for p in json.loads(
            (ROOT/'foc2_app_a/CMakePresets.json').read_text())['configurePresets']}
        for old, new in PAIRS:
            self.assertEqual(presets[new]['inherits'], old)
            self.assertEqual(presets[new]['cacheVariables'],
                             {'PW_TARGET_UNIT_TESTS': 'OFF', 'PW_LOG_STORE_SLOTS': '48'})
        cm = (ROOT/'foc2_app_a/CMakeLists.txt').read_text()
        self.assertRegex(cm, r'option\(PW_TARGET_UNIT_TESTS [^\n]+ ON\)')
        self.assertIn('set(PW_LOG_STORE_SLOTS "64" CACHE STRING', cm)
        for count, ok in ((48, True), (64, True), (0, False), (47, False), (65, False)):
            code = '#include "pw_log_store.h"\n'
            if ok:
                code += '_Static_assert(PW_LOG_TEXT_BYTES == 192, "wire size");\n'
                code += f'_Static_assert(PW_LOG_STORE_CAPACITY == {count}, "capacity");\n'
            p = subprocess.run([GCC, '-std=c11', '-fsyntax-only', '-x', 'c', '-',
                '-DPW_LOG_STORE_CAPACITY='+str(count), '-I', str(ROOT/'firmware_common')],
                input=code, text=True, capture_output=True)
            self.assertEqual(p.returncode == 0, ok, p.stderr)


if __name__ == '__main__':
    unittest.main()
