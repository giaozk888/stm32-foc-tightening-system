"""Offline-only actual C execution and A/B integration contracts."""

from app_source_view import read_app_source
from pathlib import Path
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]
GCC = r'D:\Qt\Tools\mingw1310_64\bin\gcc.exe'

class MedianControlTests(unittest.TestCase):
    def compile_run(self, name, sources, defines=()):
        out = ROOT / 'tests/foc_current_zero_build' / (name + '.exe')
        out.parent.mkdir(exist_ok=True)
        subprocess.run([GCC, '-std=c11', '-O2', '-Wall', '-Wextra', '-Werror',
                        '-pedantic', '-UNDEBUG', '-I', str(ROOT/'firmware_common'),
                        *defines, *(str(ROOT/p) for p in sources), '-o', str(out)], check=True)
        subprocess.run([str(out)], check=True, capture_output=True, text=True)

    def test_actual_formal_zero_filter(self):
        self.compile_run('run_median', ['tests/foc_run_zero_median_host.c'])

    def test_actual_isolated_binding_median_and_raw(self):
        sources = ['tests/foc_current_zero_port_host.c', 'firmware_common/foc_current_zero.c']
        self.compile_run('raw_port', sources)
        self.compile_run('median_port', sources + ['firmware_common/foc_zero_median.c'],
                         ['-DFOC_ISOLATED_CONCURRENCY=1', '-DFOC_ZERO_MEDIAN_COMPUTE_ONLY=1'])

    def test_both_slots_use_shared_primitive_and_publish_after_validation(self):
        for slot in 'ab':
            src = read_app_source(ROOT/f'foc2_app_{slot}/Core/Src/main.c',encoding='utf-8')
            calibration = src[src.index('static HAL_StatusTypeDef ADC_RunZeroCalibrate(void)\n{'):
                              src.index('void HAL_ADCEx_InjectedConvCpltCallback')]
            self.assertLess(calibration.index('FocCurrentMedian_Begin'),
                            calibration.index('run_zero_cal_active = 1U'))
            self.assertLess(calibration.index('if ((candidate_u < 1000U)'),
                            calibration.index('iu_zero_raw = candidate_u'))
            callback = src[src.index('void HAL_ADCEx_InjectedConvCpltCallback'):]
            run = callback[callback.index('if (run_zero_cal_active != 0U)'):
                           callback.index('Reconstruct W in ADC-count units:')]
            for statement in ('FocRunZeroMedian_Push', 'RUN_ZERO_MAX_DELTA_COUNTS',
                              'run_zero_sum_u += filtered_u', 'run_zero_sum_v += filtered_v',
                              'else if (admission < 0)', 'run_zero_reject_count++'):
                self.assertIn(statement, run)
            self.assertIn('return FocMedian3_U16(a, b, c);', src)
            self.assertIn('CURRENT_REJECT_STREAK_LIMIT', src)
            self.assertIn('fabsf(iu_A) > FOC_CURRENT_TRIP_A', src)

    def test_no_filtered_success_can_enable_fixture_power(self):
        port = (ROOT/'firmware_common/isolated_concurrency.inc').read_text()
        self.assertIn('#error Median acceptance is restricted', port)
        self.assertIn('COMPUTE_ONLY=1 MOTOR_QUALIFIED=0', port)
        self.assertNotIn('PowerStage_Enable', port)
        for slot in 'ab':
            cmake = (ROOT/f'foc2_app_{slot}/CMakeLists.txt').read_text()
            self.assertIn('FOC_ZERO_MEDIAN_COMPUTE_ONLY AND NOT FOC_ISOLATED_CONCURRENCY', cmake)

    def test_every_app_masks_inherited_tick_before_crt(self):
        for slot in 'ab':
            src=(ROOT/f'foc2_app_{slot}/startup_stm32g474xx.s').read_text()
            reset=src[src.index('Reset_Handler:'):src.index('LoopForever:')]
            self.assertNotIn('#if',reset)
            self.assertLess(reset.index('cpsid i'),reset.index('bl  SystemInit'))
            self.assertLess(reset.index('0xE000E010'),reset.index('LoopCopyDataInit'))
            self.assertIn('0x0A000000',reset)
            self.assertLess(reset.index('bl __libc_init_array'),reset.index('cpsie i'))
            self.assertLess(reset.index('cpsie i'),reset.index('bl\tmain'))

if __name__ == '__main__':
    unittest.main()
