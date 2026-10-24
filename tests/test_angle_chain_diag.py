"""No hardware: actual encoder math, hand observer, diagnostic admission."""
import hashlib
import json
from pathlib import Path
import re
import subprocess
import unittest
import sys
import math
from test_torque_chain import GCC,FROZEN,function
from test_torque350_five_second import expanded

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
import electrical_angle_report as decoder
import angle_hand_collect as hand_capture


class AngleChainTests(unittest.TestCase):
    def compile_run(self,source,flags,opt):
        out=ROOT/'tests/torque_chain_build'; out.mkdir(exist_ok=True)
        exe=out/(source.stem+str(len(flags))+opt+'.exe')
        p=subprocess.run([GCC,'-std=c11',opt,'-Wall','-Wextra','-Werror',*flags,
            '-I',str(ROOT/'firmware_common'),'-I',str(ROOT/'foc2_app_a/Core/Inc'),
            str(source),'-o',str(exe)],capture_output=True,text=True)
        self.assertEqual(p.returncode,0,p.stdout+p.stderr)
        p=subprocess.run([str(exe)],capture_output=True,text=True)
        self.assertEqual(p.returncode,0,p.stdout+p.stderr)

    def test_real_observer_forward_reverse_wrap_sign_poles_and_invalid(self):
        for opt in ('-Os','-O2'):
            self.compile_run(ROOT/'tests/angle_chain_host.c',[],opt)

    def test_actual_manual_owner_requires_hand_pass_one_offset_only(self):
        for opt in ('-Os','-O2'):
            self.compile_run(ROOT/'tests/torque_chain_host.c',
                ['-DFOC_ANGLE_CHAIN_DIAG=1','-DFOC_TORQUE_CHAIN_IQ_MA=350'],opt)

    def test_hand_profile_has_no_power_admission(self):
        for opt in ('-Os','-O2'):
            # Fake functions that only a power admission would call are
            # intentionally unused when that transaction is compiled out.
            self.compile_run(ROOT/'tests/torque_chain_host.c',
                ['-DFOC_ANGLE_CHAIN_DIAG=1','-DFOC_ANGLE_HAND_ONLY=1','-Wno-unused-function'],opt)
        for slot in 'ab':
            source=expanded(slot,'ElectricalAngleHandDiagnostic')
            admit=function(source,'LatestOriginal_Admit')
            self.assertNotIn('TIM1',admit); self.assertNotIn('MotorControl_SetIq',admit)
            self.assertIn('return 0U;',admit)

    def test_control_protection_frozen_except_diagnostic_direct_clamp(self):
        for slot in 'ab':
            normal=expanded(slot,'Rundown200mADirectLimitTrial')
            for preset in ('ElectricalAngleHandDiagnostic','ElectricalZeroOffsetDiagnostic'):
                new=expanded(slot,preset)
                for name in FROZEN+('MotorControl_SetSpeed','MotorControl_SetIq',
                    'FocFp_PushRawSafety','FocOcConfirm_Push','FocFeedbackSafety_Push',
                    'ProtectedLoop_GuardIrqBody'):
                    before,after=function(normal,name),function(new,name)
                    if preset=='ElectricalZeroOffsetDiagnostic' and name in ('MotorControl_SetIq','FOC_EncoderSpeedUpdate'):
                        before=before.replace('-0.20f,','-0.35f,').replace('0.20f);','0.35f);')
                    self.assertEqual(before,after,name)
                if preset=='ElectricalAngleHandDiagnostic':
                    self.assertEqual(function(normal,'Encoder_ElectricalAngleRad'),function(new,'Encoder_ElectricalAngleRad'))
                for basename in ('foc_adc_timing_stm32.c.obj','stm32g4xx_it.c.obj'):
                    hashes=[hashlib.sha256(next((ROOT/f'foc2_app_{slot}/build/{p}').rglob(basename)).read_bytes()).hexdigest()
                        for p in ('Rundown200mADirectLimitTrial',preset)]
                    self.assertEqual(*hashes,basename)

    def test_defaults_source_mapping_and_no_persistent_zero_update(self):
        for slot in 'ab':
            text=(ROOT/f'foc2_app_{slot}/Core/Src/main.c').read_text()
            for constant in ('#define POLE_PAIRS 10U','#define ENCODER_DIRECTION (-1)',
                             '#define ELECTRICAL_ZERO_RAW 10507U'):
                self.assertIn(constant,text)
            cm=(ROOT/f'foc2_app_{slot}/CMakeLists.txt').read_text()
            for option in ('FOC_ANGLE_CHAIN_DIAG','FOC_ANGLE_HAND_ONLY'):
                self.assertRegex(cm,rf'option\({option} [^\n]+ OFF\)')
            table=json.loads((ROOT/f'foc2_app_{slot}/build/ElectricalZeroOffsetDiagnostic/compile_commands.json').read_text())
            self.assertIn('-DFOC_TORQUE_CHAIN_IQ_MA=350',table[0]['command'])
            self.assertNotIn('-DFOC_SPEED_DYNAMIC_DIAG',table[0]['command'])
        binding=(ROOT/'firmware_common/foc_angle_chain_binding.inc').read_text()
        self.assertNotIn('SAVE',binding); self.assertNotIn('Write',binding)
        self.assertIn('angle_hand.passed && angle_hand.finished',binding)
        self.assertIn('!torque_diag.used',binding)

    def hand_log(self,pairs=10,direction=-1):
        lines=[]
        for i in range(257):
            mc=(i if i<=128 else 256-i)*128
            mm=mc*360/16384; em=mm*pairs*(-direction)
            raw=(1234-mc)&16383
            lines.append(f'42 OK ANGLE ROW={i} US={1000+i*20000} RAW={raw} MC={mc} '
                f'MMDEG={int(mm*1000)} EMDEG={int(em*1000)} WRMDEG={int(((em+200)%360)*1000)}')
        lines.append('43 OK ANGLE ACTIVE=0 PASS=1 OFF=1 N=257 ERR=0 MC=0 MIN=0 MAX=16384 EERR_MDEG=1 PP=10 DIR=-1 ZERO=10507')
        return '\n'.join(lines)

    def test_file_only_hand_decoder_full_turn_ratio_forward_reverse(self):
        r=decoder.hand_report(self.hand_log())
        self.assertTrue(r['software_chain_pass'],r['reasons'])
        self.assertAlmostEqual(r['observed_electrical_to_mechanical_ratio'],10)
        self.assertEqual(r['mechanical_excursion_deg'],360)
        self.assertFalse(r['magnetic_zero_verified'])
        self.assertFalse(r['physical_pole_pairs_verified'])
        self.assertFalse(r['hardware_access'])

    def test_hand_decoder_missing_rows_wrong_direction_and_poles_fail(self):
        for text in (self.hand_log(pairs=9),self.hand_log(direction=1),
            '\n'.join(self.hand_log().splitlines()[1:]),
            self.hand_log().replace('ACTIVE=0','ACTIVE=1'),
            self.hand_log().replace('ERR=0','ERR=1'),
            self.hand_log().replace('PASS=1','PASS=0')):
            self.assertFalse(decoder.hand_report(text)['software_chain_pass'])
        with self.assertRaises(ValueError): decoder.hand_report('no data')

    def test_all_seven_offsets_rotated_vector_is_orthogonal_no_math_sign_change(self):
        source=(ROOT/'foc2_app_a/Core/Src/main.c').read_text()
        for a in (-30,-20,-10,0,10,20,30):
            for raw in (0,1,10506,10507,10508,16383):
                base=(-((raw-10507+8192)%16384-8192)*2*math.pi*10/16384)%(2*math.pi)
                theta=(base+math.radians(a))%(2*math.pi)
                alpha=-.35*math.sin(theta); beta=.35*math.cos(theta)
                self.assertAlmostEqual(alpha*math.cos(theta)+beta*math.sin(theta),0)
                self.assertAlmostEqual(-alpha*math.sin(theta)+beta*math.cos(theta),.35)
        self.assertIn('foc_id_ref_A=foc_iq_ref_A=foc_vd_V=foc_vq_V=0.0f;',
            (ROOT/'firmware_common/latest_original_fsm.inc').read_text())

    def test_hand_collector_has_no_start_offset_or_flash_command(self):
        for command in ('START','MOTOR TEST ANGLE OFFSET +10 CONFIRM','MOTOR TEST TORQUE350 CONFIRM',
                        'FW BEGIN','RESET','MOTOR TEST ANGLE READ 0 extra'):
            self.assertFalse(hand_capture.allowed(command))
        for command in ('MOTOR TEST ANGLE BEGIN','MOTOR TEST ANGLE END','MOTOR TEST ANGLE READ 35'):
            self.assertTrue(hand_capture.allowed(command))
        p=subprocess.run([sys.executable,str(ROOT/'tools/angle_hand_collect.py')],
            cwd=ROOT,capture_output=True,text=True)
        self.assertEqual(p.returncode,0,p.stdout+p.stderr)
        self.assertIn('no devices',p.stdout)

    def test_hand_collector_drains_sequential_rows_and_ends_on_overrun(self):
        class Fake:
            def __init__(self,overrun=False): self.commands=[]; self.n=0; self.active=False; self.overrun=overrun
            def query(self,command):
                self.commands.append(command)
                if command=='FW STATUS': return 'OK CURRENT=A CONFIRMED=A PENDING=-'
                if command=='MOTOR TEST STATUS': return 'OK STATE=1 USED=0 ZERO=3 FLAGS=0 FAULT=0 SD=0 MOE=0 CCER=0'
                if command=='MOTOR TEST ANGLE BEGIN': self.active=True; return 'OK ANGLE BEGIN'
                if command=='MOTOR TEST ANGLE END': self.active=False; return 'OK ANGLE END PASS=1'
                if command=='MOTOR TEST ANGLE STATUS':
                    if self.active: self.n+=13 if self.overrun else 1
                    return f'OK ANGLE OFF=1 ERR=0 PP=10 DIR=-1 ZERO=10507 N={self.n} PASS=1'
                if command.startswith('MOTOR TEST ANGLE READ '): return 'OK ANGLE ROW='+command.rsplit(' ',1)[-1]
                raise AssertionError(command)
        for overrun in (False,True):
            uart=Fake(overrun); clock=[0]
            def pause(dt): clock[0]+=dt
            if overrun:
                with self.assertRaisesRegex(RuntimeError,'overrun'):
                    hand_capture.collect(uart,5,clock=lambda:clock[0],pause=pause)
            else:
                count=hand_capture.collect(uart,5,clock=lambda:clock[0],pause=pause)
                self.assertGreater(count,200)
            self.assertIn('MOTOR TEST ANGLE END',uart.commands)
            self.assertTrue(all(hand_capture.allowed(c) for c in uart.commands))


if __name__=='__main__': unittest.main()
