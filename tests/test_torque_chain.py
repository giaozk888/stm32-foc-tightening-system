"""Torque chain consistency / real compiled owner / offline binary regressions."""
import hashlib
import json
import math
from pathlib import Path
import re
import struct
import subprocess
import sys
import unittest
from unittest.mock import patch
from test_voltage_x2 import function
from test_rundown_startup_decode import make_trace
from test_rundown_isolation import FROZEN
from test_rundown_established import extract_braces

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
import torque_chain_decode as decode
import rundown_startup_decode as startup
GCC=r'D:\Qt\Tools\mingw1310_64\bin\gcc.exe'


class TorqueChainTests(unittest.TestCase):
    def test_compiled_real_manual_admission_and_owner(self):
        out=ROOT/'tests/torque_chain_build'; out.mkdir(exist_ok=True)
        for magnitude,opt in ((50,'-Os'),(50,'-O2'),(100,'-Os'),(100,'-O2'),(200,'-Os'),(200,'-O2')):
            exe=out/(str(magnitude)+opt+'.exe')
            result=subprocess.run([GCC,'-std=c11',opt,'-Wall','-Wextra','-Werror',
                '-DFOC_TORQUE_CHAIN_IQ_MA='+str(magnitude),
                '-I',str(ROOT/'firmware_common'),'-I',str(ROOT/'foc2_app_a/Core/Inc'),
                str(ROOT/'tests/torque_chain_host.c'),
                '-o',str(exe)],capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            result=subprocess.run([str(exe)],capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)

    def test_phase_clarke_inverse_chain_and_defaults(self):
        for slot in 'ab':
            text=(ROOT/f'foc2_app_{slot}/Core/Src/main.c').read_text()
            self.assertIn('#define POLE_PAIRS 10U',text)
            self.assertIn('#define ENCODER_DIRECTION (-1)',text)
            self.assertIn('#define ELECTRICAL_ZERO_RAW 10507U',text)
            self.assertIn('i_alpha = iu_A;',text)
            self.assertIn('i_beta = (iu_A + 2.0f * iv_A) * 0.57735026919f;',text)
            self.assertIn('id_A =  i_alpha * c + i_beta * s;',text)
            self.assertIn('iq_A = -i_alpha * s + i_beta * c;',text)
            outer=function(text,'FOC_EncoderSpeedUpdate')
            iq_block=extract_braces(outer,outer.index('else if (mode == MOTOR_MODE_IQ)'))
            iq_code=re.sub(r'/\*.*?\*/','',iq_block,flags=re.S)
            self.assertNotIn('run_speed_pi',iq_code)
            self.assertIn('ClampFloat(motor_iq_command_A',iq_code)
            cm=(ROOT/f'foc2_app_{slot}/CMakeLists.txt').read_text()
            self.assertRegex(cm,r'option\(FOC_TORQUE_CHAIN_DIAG [^\n]+ OFF\)')
            normal=json.loads((ROOT/f'foc2_app_{slot}/build/RundownGuardTrial/compile_commands.json').read_text())
            self.assertNotIn('-DFOC_TORQUE_CHAIN_DIAG',normal[0]['command'])
            source=(ROOT/'firmware_common/foc_adc_timing_stm32.c').read_text()
            for index in range(3): self.assertIn(f'TIM1->CCR{index+1}=phase[{index}];',source)
            self.assertEqual(len(re.findall(r'TIM1->CCR[123]=phase\[[012]\];',source)),3)
            irq=(ROOT/'firmware_common/protected_adc_irq.inc').read_text()
            self.assertIn('u=(uint16_t)hadc1.Instance->JDR1',irq)
            self.assertIn('v=(uint16_t)hadc2.Instance->JDR1',irq)
            msp=(ROOT/f'foc2_app_{slot}/Core/Src/stm32g4xx_hal_msp.c').read_text()
            for pin,signal in (('PC0','TIM1_CH1'),('PC1','TIM1_CH2'),('PC2','TIM1_CH3'),
                               ('PB13','TIM1_CH1N'),('PB0','TIM1_CH2N'),('PB1','TIM1_CH3N'),
                               ('PA0','ADC1_IN1'),('PA1','ADC2_IN2')):
                self.assertIn(f'{pin}     ------> {signal}',msp)
            # Local-only gate is outside the diagnostic command dispatcher.
            self.assertIn('protocol_reply_route_active || !protocol_esp_ping_uart_local',text)
        # Park/inverse Park round trip independent of angle and Iq sign.
        for theta in (0,.2,1.57,3.2,6.1):
            for iq in (-.1,-.05,.05,.1):
                a=-iq*math.sin(theta); b=iq*math.cos(theta)
                self.assertAlmostEqual(a*math.cos(theta)+b*math.sin(theta),0)
                self.assertAlmostEqual(-a*math.sin(theta)+b*math.cos(theta),iq)
        # Signed mechanical direction and electrical angle have the same sign.
        for delta in (-1,1):
            self.assertEqual(math.copysign(1,-delta*10),math.copysign(1,-delta))

    def test_frozen_control_and_safety_functions_identical(self):
        for slot in 'ab':
            expanded=[]
            for preset in ('RundownDiagnosticTrial','TorqueChain100mADiagnostic'):
                base=ROOT/f'foc2_app_{slot}/build/{preset}'
                commands=json.loads((base/'compile_commands.json').read_text())
                command=next(x['command'] for x in commands if x['file'].endswith('/Core/Src/main.c'))
                result=subprocess.run(re.sub(r' -o \S+ -c ',' -E -P ',command),cwd=base,
                    capture_output=True,text=True,check=True)
                expanded.append(result.stdout)
            for name in FROZEN+('MotorControl_SetIq','FocFp_PushRawSafety','FocOcConfirm_Push',
                               'FocFeedbackSafety_Push','ProtectedLoop_GuardIrqBody'):
                self.assertEqual(function(expanded[0],name),function(expanded[1],name),name)
            for basename in ('foc_adc_timing_stm32.c.obj','stm32g4xx_it.c.obj'):
                hashes=[]
                for preset in ('RundownDiagnosticTrial','TorqueChain100mADiagnostic'):
                    path=next((ROOT/f'foc2_app_{slot}/build/{preset}').rglob(basename))
                    hashes.append(hashlib.sha256(path.read_bytes()).hexdigest())
                self.assertEqual(hashes[0],hashes[1],basename)

    def test_binary_statistics_direction_and_no_auto_zero(self):
        data=make_trace()
        for i in range(33): struct.pack_into('<I',data,i*startup.FRAME.size,i*8000)
        report=decode.analyze(data,1,0)
        stats=report['statistics']
        self.assertAlmostEqual(stats['mean_abs_Id_A'],.02,places=6)
        self.assertAlmostEqual(stats['mean_Iq_A'],.1,places=6)
        self.assertAlmostEqual(stats['Id_Iq_abs_ratio'],.2,places=6)
        self.assertEqual(stats['opposite_direction_intervals'],0)
        self.assertEqual(stats['expected_direction_intervals'],31)
        self.assertFalse(report['automatic_zero_selection']); self.assertFalse(report['hardware_access'])
        negative=decode.analyze(data,-1,-5)
        self.assertEqual(negative['statistics']['opposite_direction_intervals'],31)
        with self.assertRaises(ValueError): decode.analyze(data,1,90)
        with self.assertRaises(ValueError): startup.decode(data) # distinct cadence

    def test_metadata_matches_compiled_abi_and_rejects_bad_elf(self):
        class Result: stdout='20000020 00000014 b torque_diag\n'
        meta=decode.META.pack(100,1,-5,1,0,1,0,0,0,0)
        with patch.object(decode.subprocess,'run',return_value=Result()):
            report=decode.metadata('matching.elf',bytes(32)+meta,0x20000000,'nm')
            self.assertEqual(report['offset_electrical_deg'],-5)
            self.assertEqual(report['sign'],1)
            with self.assertRaises(ValueError): decode.metadata('x.elf',bytes(10),0x20000000,'nm')
        Result.stdout='20000020 00000018 b torque_diag\n'
        with patch.object(decode.subprocess,'run',return_value=Result()):
            with self.assertRaises(ValueError): decode.metadata('x.elf',bytes(100),0x20000000,'nm')


if __name__=='__main__': unittest.main()
