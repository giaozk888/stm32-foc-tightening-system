import hashlib
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
import six_signal_acceptance as host
from test_feedback_safety_builds import symbols, CORE_HANDLERS, OBJDUMP
import subprocess
import re
import struct
import six_signal_swd_deploy as recovery
import zlib
import six_signal_capture as capture


def reaches_switch_off(elf,handler,visited=None):
    visited=set() if visited is None else visited
    if handler in visited or len(visited)>len(CORE_HANDLERS): return False
    asm=subprocess.run([OBJDUMP,'-d','--disassemble='+handler,str(elf)],
                       capture_output=True,text=True,check=True).stdout
    targets=re.findall(r'\b(?:bl|blx|b(?:\.[nw])?)\s+[0-9a-fA-F]+\s+<([^>+]+)>',asm)
    return 'SwitchFeedback_EmergencyOff' in targets or any(
        name in CORE_HANDLERS and reaches_switch_off(elf,name,visited|{handler}) for name in targets)


class SixSignalTests(unittest.TestCase):
    def test_linked_identity_guards_and_configuration(self):
        data=host.image(); build=host.IMAGE.parent; elf=build/'foc2.elf'
        syms=symbols(elf)
        self.assertEqual(syms['TIM7_DAC_IRQHandler'][1],'T')
        self.assertEqual(struct.unpack_from('<I',data,(16+55)*4)[0],syms['TIM7_DAC_IRQHandler'][0]|1)
        for handler in (*CORE_HANDLERS,'HAL_ADC_ErrorCallback','vApplicationMallocFailedHook',
                        'vApplicationStackOverflowHook','Error_Handler'):
            self.assertTrue(reaches_switch_off(elf,handler),handler)
        cache=(build/'CMakeCache.txt').read_text('utf-8')
        for option in ('SWITCH_SIGNAL_ONLY_DIAGNOSTIC','SWITCH_FEEDBACK_DIAGNOSTIC',
                       'ZERO_RETEST_BOOT','ZERO_MEDIAN_DIAGNOSTIC','UART_FIRMWARE_TRANSFER'):
            self.assertIn(option+':BOOL=ON',cache)
        self.assertIn('FOC_FEEDBACK_SAFETY_BINDING:BOOL=OFF',cache)
        self.assertEqual(hashlib.sha256((ROOT/'foc2_app_b/build/FeedbackBudget2x20261013/foc2.bin').read_bytes()).hexdigest(),host.OLD_B)

    def test_wrong_baseline_refused(self):
        for slot,gen in (('A',457),('B',456),('B',460)):
            with patch.object(host,'locked_baseline',return_value=dict(current=slot,generation=gen)):
                with self.assertRaises(RuntimeError): host.baseline_identity(b'')

    def test_no_power_commands_or_captures(self):
        class Port:
            def write(self,data): raise TimeoutError('lost ACK')
        uart=host.Console(Port())
        for text in ('SWITCH START BRIDGE','SWITCH WAVE VERIFIED','SWITCH START PWM',
                     'SWITCH START OFF','ZERO SAMPLE','START','CLEAR','BOOT A'):
            with self.assertRaises(ValueError): uart.query(text)
        with self.assertRaises(TimeoutError): uart.query('SWITCH START GUARD')
        with self.assertRaises(ValueError): uart.query('SWITCH START GUARD')
        with self.assertRaises(TimeoutError): uart.command('FW END')
        with self.assertRaises(ValueError): uart.command('FW END')

    def test_status_rejects_bridge_compiled_or_high_sd(self):
        good='PROFILE=OPEN_LOAD_ONLY MOTOR_READY=0 BRIDGE_COMPILED=0 ACTIVE=0 SD=0 MOE=0 CCER=0 CEN=0'
        self.assertEqual(host.signal_status(good)['SD'],'0')
        for bad in (good.replace('BRIDGE_COMPILED=0','BRIDGE_COMPILED=1'),good.replace('SD=0','SD=1')):
            with self.assertRaises(RuntimeError): host.signal_status(bad)

    def test_swd_request_only_normal_trial_and_inactive_programming(self):
        data=host.image(); words=recovery.mailbox(data)
        self.assertEqual(words[:5],(0x584F424D,1,2,2,1))
        self.assertEqual(words[5:7],(len(data),zlib.crc32(data)))
        self.assertEqual(words[7],zlib.crc32(struct.pack('<7I',*words[:7])))
        self.assertIn('reset halt',recovery.safe_halt_commands())
        self.assertNotIn('reset run',recovery.safe_halt_commands())
        code=(ROOT/'tools/six_signal_swd_deploy.py').read_text('utf-8')
        self.assertEqual(code.count('flash write_image erase'),1)
        self.assertIn('flash write_image erase {{{profile.IMAGE.as_posix()}}} 0x08008000 bin',code)
        self.assertLess(code.index("row['staged_flash'] = compare_flash"),code.index("row['trial_request_attempted'] = True"))
        self.assertIn("row['before_fault'] != prior['final_fault']",code)

    def test_capture_console_no_bridge_or_repeat(self):
        class Port:
            def write(self,data): raise TimeoutError('lost ACK')
        uart=capture.Console(Port())
        for text in ('FW END','START','CLEAR','SWITCH START BRIDGE','SWITCH WAVE VERIFIED',
                     'SWITCH START GUARD','BENCH PROTECTION TEST TIMEOUT'):
            with self.assertRaises(ValueError): uart.query(text)
        with self.assertRaises(ValueError): uart.command('FW END')
        for text in ('ZERO SAMPLE','SWITCH START OFF','SWITCH START PWM'):
            with self.assertRaises(TimeoutError): uart.query(text)
            with self.assertRaises(ValueError): uart.query(text)

    def test_capture_supply_and_receipt(self):
        self.assertEqual(capture.deployment()['final_fw']['GEN'],'460')
        good='VALID=1 VBUS_EST_MV=12000 VDDA_BOOT_MV=3300'
        self.assertEqual(capture.supply(good)['VALID'],'1')
        for bad in (good.replace('12000','0'),good.replace('12000','15000'),
                    good.replace('3300','3700'),good.replace('VALID=1','VALID=0')):
            with self.assertRaises(RuntimeError): capture.supply(bad)


if __name__=='__main__': unittest.main()
