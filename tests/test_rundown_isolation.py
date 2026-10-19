"""Compare the new application-only candidate against pre-change main.c.
Uses local HEAD source and preprocessors; never connects to a device.
"""
import hashlib
import json
from pathlib import Path
import re
import subprocess
import unittest
from test_voltage_x2 import function

ROOT=Path(__file__).resolve().parents[1]
BASELINE='5eeae2ebf55778b6300949874f4ad7508cc5259e'
OUT=ROOT/'tests/rundown_isolation_build'
FROZEN=('FOC_CurrentLoopStep','FOC_EncoderSpeedUpdate','FOC_ResetController',
        'ProtectedLoop_PwmEntry','ProtectedLoop_PwmStage','ProtectedLoop_AdcIrq',
        'ProtectedLoop_Pair','FocCurrentValidation_Push','FocFp_Poll',
        'TIM7_DAC_IRQHandler','ProtectedLoop_TimerHealthy')


class IsolationTests(unittest.TestCase):
    def test_normal_control_kernels_and_warnings_unchanged_against_git_baseline(self):
        OUT.mkdir(exist_ok=True)
        for slot in 'ab':
            root=ROOT/f'foc2_app_{slot}'
            base=root/'build/RundownGuardTrial'
            commands=json.loads((base/'compile_commands.json').read_text())
            command=next(x['command'] for x in commands if x['file'].endswith('/Core/Src/main.c'))
            old=subprocess.run(['git','show',f'{BASELINE}:foc2_app_{slot}/Core/Src/main.c'],
                               cwd=ROOT,capture_output=True,text=True,check=True).stdout
            path=OUT/f'baseline_{slot}.c'; path.write_text(old,encoding='utf-8')
            oldcommand=command.rsplit(' -c ',1)[0]+' -c "'+path.as_posix()+'"'
            self.assertNotEqual(command,oldcommand)
            expanded=[]; warnings=[]
            for cmd in (oldcommand,command):
                pp=subprocess.run(re.sub(r' -o \S+ -c ',' -E -P ',cmd),cwd=base,
                    capture_output=True,text=True,check=True)
                expanded.append(pp.stdout)
                check=subprocess.run(re.sub(r' -o \S+ -c ',' -fsyntax-only ',cmd),cwd=base,
                    capture_output=True,text=True,check=True)
                warnings.append(set(re.findall(r'warning: (.*)',check.stderr)))
            for name in FROZEN:
                before,after=function(expanded[0],name),function(expanded[1],name)
                if name=='FOC_EncoderSpeedUpdate':
                    # 2026-10-19 explicit user request: only the direct IQ
                    # clamp moves 150 -> 200mA. All other body text is frozen.
                    pattern=r'(ClampFloat\(motor_iq_command_A,\s*)-0\.15f,(\s*)0\.15f(\);)'
                    before,count=re.subn(pattern,r'\g<1>-0.20f,\g<2>0.20f\g<3>',before)
                    self.assertEqual(count,1)
                self.assertEqual(before,after,name)
            self.assertFalse(warnings[1]-warnings[0],warnings[1]-warnings[0])

    def test_adc_timing_object_identical_and_slot_boundaries_unchanged(self):
        for slot in 'ab':
            root=ROOT/f'foc2_app_{slot}/build'
            objects=[]
            for preset in ('SpeedBrakeTrackTrial','RundownGuardTrial','RundownDiagnosticTrial'):
                path=next((root/preset).rglob('foc_adc_timing_stm32.c.obj'))
                objects.append(hashlib.sha256(path.read_bytes()).hexdigest())
                self.assertLessEqual((root/preset/'foc2.bin').stat().st_size,229376)
            self.assertEqual(len(set(objects)),1)
            current=(ROOT/f'foc2_app_{slot}/STM32G474XX_FLASH.ld').read_bytes()
            baseline=subprocess.run(['git','show',f'{BASELINE}:foc2_app_{slot}/STM32G474XX_FLASH.ld'],
                cwd=ROOT,capture_output=True,check=True).stdout
            self.assertEqual(current.replace(b'\r\n',b'\n'),baseline)

    def test_extended_diagnostics_do_not_change_foc_math_or_irq_kernels(self):
        for slot in 'ab':
            expanded=[]
            for preset in ('RundownGuardTrial','RundownDiagnosticTrial'):
                base=ROOT/f'foc2_app_{slot}/build/{preset}'
                commands=json.loads((base/'compile_commands.json').read_text())
                command=next(x['command'] for x in commands if x['file'].endswith('/Core/Src/main.c'))
                expanded.append(subprocess.run(re.sub(r' -o \S+ -c ',' -E -P ',command),
                    cwd=base,capture_output=True,text=True,check=True).stdout)
            for name in FROZEN:
                before,after=[function(x,name) for x in expanded]
                if name=='FOC_EncoderSpeedUpdate':
                    # Only these accepted-word diagnostic assignments differ.
                    after=re.sub(r'\s*rundown_encoder_delta=[^;]+;\s*rundown_encoder_dt_us=[^;]+;', '',after)
                    before=re.sub(r'\s+',' ',before); after=re.sub(r'\s+',' ',after)
                self.assertEqual(before,after,name)


if __name__=='__main__': unittest.main()
