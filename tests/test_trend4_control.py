"""Actual firmware four-point core, runtime include and locked zero binding."""

from app_source_view import read_app_source
from pathlib import Path
import subprocess
import unittest
import test_trend_spike_candidate as reference
import test_median_control_integration as binding

ROOT=Path(__file__).resolve().parents[1]
GCC=r'D:\Qt\Tools\mingw1310_64\bin\gcc.exe'

class ProductionTrend4Tests(reference.TrendCandidateTests):
    @classmethod
    def setUpClass(cls):
        out=ROOT/'tests/foc_current_zero_build/trend4_replay.exe'
        out.parent.mkdir(exist_ok=True)
        subprocess.run([GCC,'-std=c11','-O2','-Wall','-Wextra','-Werror',
            '-DFOC_CURRENT_SPIKE_ONLY=1','-DFOC_CURRENT_TREND4=1',
            '-I',str(ROOT/'firmware_common'),
            str(ROOT/'tests/foc_current_spike_replay_host.c'),'-o',str(out)],check=True)
        cls.exes={'quadratic4_30_40':out}

    def test_actual_runtime_zero_and_raw_trip(self):
        binding.MedianControlTests().compile_run('trend4_runtime',[
            'tests/foc_current_trend4_host.c','firmware_common/foc_current_zero.c',
            'firmware_common/foc_zero_median.c'],[
            '-DFOC_CURRENT_SPIKE_ONLY=1','-DFOC_CURRENT_TREND4=1'])

    def test_actual_isolated_zero_binding(self):
        binding.MedianControlTests().compile_run('trend4_port',[
            'tests/foc_current_zero_port_host.c','firmware_common/foc_current_zero.c',
            'firmware_common/foc_zero_median.c'],[
            '-DFOC_ISOLATED_CONCURRENCY=1','-DFOC_ZERO_MEDIAN_COMPUTE_ONLY=1',
            '-DFOC_CURRENT_SPIKE_ONLY=1','-DFOC_CURRENT_TREND4=1'])

    def test_ab_control_and_safety_contracts(self):
        for slot in 'ab':
            source=read_app_source(ROOT/f'foc2_app_{slot}/Core/Src/main.c','utf-8')
            function=source[source.index('static void FOC_CurrentLoopStep(uint16_t u_raw, uint16_t v_raw,\n'):
                            source.index('static HAL_StatusTypeDef FOC_EncoderSpeedUpdate(float dt_s)\n{')]
            self.assertIn('FocTrend4_RawTrip(u_physical, v_physical',function)
            self.assertIn('physical_trip ||',function)
            self.assertIn('theta = current_trend4_angle.center;',function)
            self.assertIn('s = sinf(encoder_theta_e_pred);',function)
            callback=source[source.index('void HAL_ADCEx_InjectedConvCpltCallback'):]
            self.assertLess(callback.index('FocTrend4Angle_Push'),callback.index('#include "foc_current_spike_runtime.inc"'))
            self.assertIn('current_spike_filter.count < FOC_CURRENT_HISTORY_PAIRS',callback)
            cmake=(ROOT/f'foc2_app_{slot}/CMakeLists.txt').read_text()
            # The separately guarded protected profile was introduced after
            # this test: retain the hard-off guard for every OTHER profile.
            self.assertIn('FOC_CURRENT_TREND4 AND NOT FOC_PROTECTED_CLOSED_LOOP AND (NOT FOC_CURRENT_SPIKE_ONLY OR NOT FOC_ISOLATED_CONCURRENCY',cmake)
            self.assertIn('FOC_PROTECTED_CLOSED_LOOP AND (NOT FOC_ADC_WINDOW OR NOT AS5047P_SPI_DMA',cmake)
            self.assertIn('NOT FOC_ZERO_MEDIAN_COMPUTE_ONLY OR FOC_ZERO_FAILURE_TRACE',cmake)

    def test_one_period_quad_delay_and_real_pulse_ambiguity(self):
        samples=[(1560,1560),(1562,1560),(1621,1560),(1563,1560)]
        self.assertEqual(self.replay('quadratic4_30_40',samples),[(2,1563,1560,1)])
        rows=self.replay('quadratic4_30_40',[(1560,1560)]*10+[(2400,1560)]+[(1560,1560)]*10)
        self.assertEqual(next(row for row in rows if row[0]==10)[1:],(1560,1560,1))

if __name__=='__main__': unittest.main()
