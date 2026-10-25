"""Offline original-control numeric/profile checks; never touches hardware."""

from app_source_view import read_app_source
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from firmware_transfer_iap import image_info


class UpdatedOriginalControl(unittest.TestCase):
    def test_presets_inherit_normal_control_not_short_test(self):
        for slot in 'ab':
            document = json.loads((ROOT / f'foc2_app_{slot}/CMakePresets.json').read_text('utf-8'))
            presets = {p['name']: p for p in document['configurePresets']}

            def resolve(name):
                preset = presets[name]
                values = resolve(preset['inherits']) if 'inherits' in preset else {}
                return {**values, **preset.get('cacheVariables', {})}

            values = resolve('OriginalClosedLoopUpdated')
            self.assertEqual(values['FOC_ORIGINAL_CLOSED_LOOP_UPDATED'], 'ON')
            for key in ('AS5047P_SPI_DMA', 'ROUTER_READ_ONLY_TRANSFER', 'CAN_CONTROL_REJECT_ONLY'):
                self.assertEqual(values[key], 'ON')
            for key in ('PW_ALLOCATOR_HYBRID', 'FOC_ADC_WINDOW', 'FOC_ISOLATED_CONCURRENCY',
                        'FOC_PROTECTED_CLOSED_LOOP', 'FOC_CURRENT_SPIKE_ONLY', 'FOC_CURRENT_TREND4'):
                self.assertEqual(values[key], 'OFF')

    def test_cmake_rejects_diagnostic_or_protection_bypass_mix(self):
        command = ['cmake', '-P', str(ROOT / 'tests/original_closed_loop_profile_guard.cmake')]
        good = subprocess.run(command, capture_output=True, text=True)
        self.assertEqual(good.returncode, 0, good.stderr)
        for option in ('FOC_PROTECTED_CLOSED_LOOP', 'FOC_CURRENT_TREND4', 'FOC_RAW_OBSERVE_ONLY',
            'FOC_FILTERED_OBSERVE_ONLY', 'FOC_ADAPTIVE_FILTER_EXPERIMENT', 'FOC_ZERO_TOTAL_BUDGET_OFF',
            'FOC_FEEDBACK_SAFETY_BINDING', 'ZERO_RETEST_BOOT', 'TIGHTEN_SPEED_X2_OFFLINE',
            'CAN_MOTOR_CONTROL_SERVICE', 'CAN_FD_EXPERIMENT', 'PW_ALLOCATOR_HYBRID'):
            result = subprocess.run(['cmake', '-DINVALID_OPTION=' + option, *command[1:]],
                                    capture_output=True, text=True)
            with self.subTest(option=option):
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('Original updated control', result.stderr)

    def test_boot_report_uses_actual_control_macros_both_slots(self):
        names = ('FOC_CURRENT_TRIP_A', 'RUN_ZERO_MAX_DELTA_COUNTS', 'FOC_TS_S',
                 'MOTOR_SPEED_IQ_LIMIT_A', 'MOTOR_DIRECT_IQ_LIMIT_A', 'FOC_VOLTAGE_LIMIT_V')
        for slot in 'ab':
            source = read_app_source(ROOT / f'foc2_app_{slot}/Core/Src/main.c','utf-8')
            arguments = []
            for name in names:
                value = re.search(r'^#define\s+' + name + r'\s+([0-9.]+f?)\b', source, re.M)[1]
                arguments.append('-D' + name + '=' + value)
            report = source[source.index('static char profile[256];'):source.index('UART_SendString(profile);')]
            for name in names:
                self.assertIn(name, report)
            with tempfile.TemporaryDirectory() as folder:
                binary = Path(folder) / 'profile.exe'
                subprocess.run([r'D:\Qt\Tools\mingw1310_64\bin\gcc.exe', '-std=c11', '-Wall',
                    '-Wextra', '-Werror', *arguments, '-I', str(ROOT / 'firmware_common'),
                    str(ROOT / 'tests/original_closed_loop_profile_host.c'), '-o', str(binary)],
                    check=True, capture_output=True, text=True)
                result = subprocess.run([str(binary)], capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_linked_images_are_normal_original_control_with_new_identity(self):
        for slot in 'ab':
            directory = ROOT / f'foc2_app_{slot}/build/OriginalClosedLoopUpdated'
            image = (directory / 'foc2.bin').read_bytes()
            self.assertEqual(image_info(image)[0], slot.upper())
            for marker in (b'ORIGINAL_UPDATED_20261015', b'START=ORIGINAL QUALIFIED=0',
                           b'Phase trip      : 4.0A; powered validation pending'):
                self.assertIn(marker, image)
            self.assertNotIn(b'Phase trip      : 2.0A unchanged', image)
            self.assertIn('.text.TighteningTask', (directory / 'foc2.map').read_text('utf-8'))
            commands = json.loads((directory / 'compile_commands.json').read_text('utf-8'))
            command = next(c['command'] for c in commands if c['file'].endswith('/Core/Src/main.c'))
            self.assertIn('-DFOC_ORIGINAL_CLOSED_LOOP_UPDATED=1', command)
            for forbidden in ('FOC_PROTECTED_CLOSED_LOOP', 'FOC_CURRENT_TREND4',
                              'FOC_RAW_OBSERVE_ONLY', 'FOC_FILTERED_OBSERVE_ONLY', 'FOC_ADC_WINDOW'):
                self.assertNotIn('-D' + forbidden + '=', command)

    def test_pinned_historical_binary_preserved(self):
        image = (ROOT / 'foc2_app_b/build/PoweredSpeedBounded20261008/foc2.bin').read_bytes()
        self.assertEqual(hashlib.sha256(image).hexdigest(),
                         '8b57f03e359f532338361b5fa8e53540d4afa829bb3acf3793e24f0b9b9a604c')


if __name__ == '__main__':
    unittest.main()
