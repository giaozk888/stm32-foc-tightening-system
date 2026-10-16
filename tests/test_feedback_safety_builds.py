"""Inspect local linked artifacts only; never connect to a board or programmer."""
from pathlib import Path
import hashlib
import re
import struct
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]
NM = r'D:\software\arm\bin\arm-none-eabi-nm.exe'
OBJDUMP = r'D:\software\arm\bin\arm-none-eabi-objdump.exe'

def symbols(elf):
    listing = subprocess.run([NM, str(elf)], capture_output=True, text=True, check=True).stdout
    return {name: (int(address, 16), kind) for address, kind, name in
            re.findall(r'^([0-9a-fA-F]+) ([A-Za-z]) (\S+)$', listing, re.M)}

CORE_HANDLERS = {'NMI_Handler', 'HardFault_Handler', 'MemManage_Handler',
                 'BusFault_Handler', 'UsageFault_Handler'}

def reaches_emergency_off(elf, handler, visited=None):
    """Follow only audited core-handler trampolines created by GCC folding."""
    visited = set() if visited is None else visited
    if handler in visited or len(visited) >= len(CORE_HANDLERS) + 1:
        return False
    visited = visited | {handler}
    asm = subprocess.run([OBJDUMP, '-d', '--disassemble='+handler, str(elf)],
                         capture_output=True, text=True, check=True).stdout
    targets = re.findall(r'\b(?:bl|blx|b(?:\.[nw])?)\s+[0-9a-fA-F]+\s+<([^>+]+)>', asm)
    return 'FocFeedbackBinding_EmergencyOff' in targets or any(
        target in CORE_HANDLERS and reaches_emergency_off(elf, target, visited)
        for target in targets)

class FeedbackBuildTests(unittest.TestCase):
    BUILD = 'FeedbackSafety20261013'
    def test_linked_ab_guard_vector_core_fault_hooks_and_hard_off_config(self):
        for slot in 'ab':
            with self.subTest(slot=slot):
                build = ROOT / f'foc2_app_{slot}/build/{self.BUILD}'
                elf = build / 'foc2.elf'
                sym = symbols(elf)
                address, kind = sym['TIM7_DAC_IRQHandler']
                self.assertEqual(kind, 'T')  # Strong handler, not startup weak default.
                image = (build / 'foc2.bin').read_bytes()
                self.assertEqual(struct.unpack_from('<I', image, (16+55)*4)[0], address | 1)
                self.assertLessEqual(len(image), 224*1024)
                for handler in ('NMI_Handler', 'HardFault_Handler', 'MemManage_Handler',
                                'BusFault_Handler', 'UsageFault_Handler', 'HAL_ADC_ErrorCallback'):
                    self.assertTrue(reaches_emergency_off(elf, handler), handler)
                cache = (build / 'CMakeCache.txt').read_text('utf-8')
                for macro in ('FOC_FEEDBACK_SAFETY_BINDING', 'FOC_CURRENT_TREND4',
                              'FOC_CURRENT_SPIKE_ONLY', 'FOC_ISOLATED_CONCURRENCY',
                              'FOC_ZERO_MEDIAN_COMPUTE_ONLY', 'FOC_ADC_WINDOW', 'AS5047P_SPI_DMA'):
                    self.assertIn(macro+':BOOL=ON', cache)
                for macro in ('FOC_RAW_OBSERVE_ONLY', 'FOC_FILTERED_OBSERVE_ONLY',
                              'SWITCH_FEEDBACK_DIAGNOSTIC', 'ZERO_RETEST_BOOT'):
                    self.assertIn(macro+':BOOL=OFF', cache)

    def test_default_ab_excludes_binding_and_previous_acceptance_images_preserved(self):
        for slot in 'ab':
            build = ROOT / f'foc2_app_{slot}/build/FeedbackDefaultCheck20261013'
            self.assertIn('FOC_FEEDBACK_SAFETY_BINDING:BOOL=OFF',
                          (build / 'CMakeCache.txt').read_text('utf-8'))
            sym = symbols(build / 'foc2.elf')
            self.assertNotIn('FocFeedbackBinding_EmergencyOff', sym)
            self.assertNotEqual(sym['TIM7_DAC_IRQHandler'][1], 'T')
        previous = {
            'foc2_app_a/build/CurrentObserveOnly20261013/foc2.bin':
                '350408d649507d3b9a360b778bedd14be88c433fde27a811f35938888e5cf241',
            'foc2_app_b/build/SwitchTrendCompare20261013/foc2.bin':
                'f725799506142c1cb55d47ce39069e14fc1fa3519508f0374528c628cf20fc0f',
        }
        for name, digest in previous.items():
            self.assertEqual(hashlib.sha256((ROOT / name).read_bytes()).hexdigest(), digest)

class FeedbackDoubledBudgetBuildTests(FeedbackBuildTests):
    BUILD = 'FeedbackBudget2x20261013'

    def test_new_budget_visible_and_previous_guardian_artifacts_unchanged(self):
        previous = {
            'a': 'faa28d5df9186315c3302bc6a7f59a517a40a86de48a220fc17027c76603ff73',
            'b': 'cdd2e3f21ad3806a828c19c690b54951ac4344058434848eeed762051a112591',
        }
        header=(ROOT/'firmware_common/foc_feedback_binding_stm32.h').read_text('utf-8')
        self.assertIn('FOC_FB_REPAIR_HITS_PER_32 = 6U',header)
        self.assertIn('FOC_FB_REPAIR_STREAK = 4U',header)
        for slot,digest in previous.items():
            old=ROOT/f'foc2_app_{slot}/build/FeedbackSafety20261013/foc2.bin'
            self.assertEqual(hashlib.sha256(old.read_bytes()).hexdigest(),digest)
            data=(ROOT/f'foc2_app_{slot}/build/{self.BUILD}/foc2.bin').read_bytes()
            self.assertIn(b'REPAIR_MAX=%u STREAK_MAX=%u',data)
            self.assertIn(b'COMPUTE_ONLY=1 MOTOR_QUALIFIED=0',data)
            self.assertIn(b'SD=MOE=CCER=0',data)
            self.assertNotIn(b'OPEN_LOAD_ONLY',data)
            def options(folder):
                cache=(folder/'CMakeCache.txt').read_text('utf-8')
                return {key: value for key, value in re.findall(
                    r'^([A-Z][A-Z0-9_]*):(?:BOOL|STRING)=(.*)$',cache,re.M)
                    if not key.startswith('CMAKE_')}
            old_dir=ROOT/f'foc2_app_{slot}/build/FeedbackSafety20261013'
            new_dir=ROOT/f'foc2_app_{slot}/build/{self.BUILD}'
            self.assertEqual(options(old_dir),options(new_dir))

if __name__ == '__main__': unittest.main()
