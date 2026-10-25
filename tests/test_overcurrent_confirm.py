"""Offline candidate tests, explicitly not powered protection qualification."""

from app_source_view import read_app_source
from pathlib import Path
import unittest
import test_median_control_integration as binding
ROOT=Path(__file__).resolve().parents[1]

class OvercurrentConfirmTests(unittest.TestCase):
    def test_actual_candidate_c_kernel(self):
        binding.MedianControlTests().compile_run('oc_confirm',
            ['tests/foc_overcurrent_confirm_host.c'])

    def test_candidate_cannot_silently_change_application_gate(self):
        for slot in 'ab':
            src=read_app_source(ROOT/f'foc2_app_{slot}/Core/Src/main.c','utf-8')
            self.assertNotIn('foc_overcurrent_confirm.h',src)
            self.assertNotIn('FocOcConfirm_',src)
            self.assertIn('physical_trip ||',src)
            self.assertIn('(fabsf(iu_A) > FOC_CURRENT_TRIP_A)',src)
        header=(ROOT/'firmware_common/foc_overcurrent_confirm.h').read_text('utf-8')
        for banned in ('malloc(', 'HAL_', 'TIM1->', 'PWM_SetDuty', 'foc_enable ='):
            self.assertNotIn(banned,header)

if __name__=='__main__': unittest.main()
