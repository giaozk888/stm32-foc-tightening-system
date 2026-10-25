"""Offline refactor checks; no board transport or hardware actions."""
from pathlib import Path
import hashlib
import json
import re
import unittest
from app_source_view import read_app_source
from app_a_source_layout import app_source_files

ROOT=Path(__file__).resolve().parents[1]
LAYOUT=json.loads((ROOT/'foc2_app_a/Core/Src/App/layout.json').read_text())


class LayoutTests(unittest.TestCase):
    def test_actual_split_bodies_reconstruct_original_without_algorithm_edits(self):
        current=read_app_source(ROOT/'foc2_app_a/Core/Src/main.c')
        self.assertEqual(hashlib.sha256(current.encode('utf-8')).hexdigest(),
            LAYOUT['original_lf_sha256'])

    def test_main_is_boot_composition_not_a_second_control_owner(self):
        text=(ROOT/'foc2_app_a/Core/Src/main.c').read_text()
        self.assertLess(len(text.splitlines()),250)
        self.assertNotIn('switch (',text);self.assertNotIn('SpeedScurve_Step(',text)
        self.assertNotIn('static HAL_StatusTypeDef FOC_EncoderSpeedUpdate(',text)
        self.assertIn('xTaskCreate(StartupTask,',text)
        self.assertLess(text.index('SystemClock_Config();'),text.index('MX_GPIO_Init();'))
        self.assertLess(text.index('MX_ADC1_Init();'),text.index('MX_ADC2_Init();'))
        self.assertIn('PowerStage_Disable();',text)

    def test_each_private_module_has_single_explicit_owner(self):
        text=(ROOT/'foc2_app_a/Core/Src/main.c').read_text()
        m=json.loads((ROOT/'foc2_app_a/Core/Src/App/layout.json').read_text())
        self.assertEqual(len(m['modules']),22)
        for item in m['modules']:
            self.assertEqual(text.count('#include "'+item['include']+'"'),1)
            self.assertTrue((ROOT/item['path']).is_file())
        cm=(ROOT/'foc2_app_a/CMakeLists.txt').read_text()
        self.assertEqual(cm.count('PRIVATE Core/Src/App/board/app_board.c'),1)

    def test_real_board_exports_match_original_cold_initializers(self):
        header=(ROOT/'foc2_app_a/Core/Src/App/board/app_board.h').read_text()
        source=(ROOT/'foc2_app_a/Core/Src/App/board/app_board.c').read_text()
        for fn in ('SystemClock_Config','MX_GPIO_Init','MX_TIM1_Init','MX_SPI1_Init','MX_LPUART1_UART_Init','MX_ADC1_Init','MX_ADC2_Init'):
            self.assertIn('void '+fn+'(void);',header)
            self.assertIn('void '+fn+'(void)\n{',source)
        self.assertNotIn('MotorControlTask',source);self.assertNotIn('HAL_NVIC_SetPriority(',source)
        self.assertIn('DRIVER_SD_Pin, GPIO_PIN_RESET',source)

    def test_b_source_and_build_policy_not_modified(self):
        pins=LAYOUT['preserved_source_pins']
        for rel in ('foc2_app_b/Core/Src/main.c','foc2_app_b/CMakeLists.txt'):
            self.assertEqual(hashlib.sha256((ROOT/rel).read_bytes()).hexdigest(),pins[rel])

    def test_historical_reader_reads_current_module_bodies_not_backup(self):
        source=(ROOT/'tools/app_a_source_layout.py').read_text()
        self.assertNotIn('refactor_backups',source)
        self.assertIn('(ROOT/item[\'path\']).read_text()',source)

    def test_new_manifests_cover_actual_bindings_and_board(self):
        inputs=app_source_files()
        self.assertEqual(len(inputs),len(set(inputs)))
        self.assertIn(ROOT/'foc2_app_a/Core/Src/App/board/app_board.c',inputs)
        self.assertIn(ROOT/'foc2_app_a/Core/Src/App/board/app_board.h',inputs)
        self.assertEqual(sum(p.suffix=='.inc' for p in inputs),22)
        self.assertTrue(all(p.is_file() for p in inputs))


if __name__=='__main__':unittest.main()
