
from app_source_view import read_app_source
from pathlib import Path
import subprocess
import unittest

ROOT=Path(__file__).resolve().parents[1]
GCC=r'D:\Qt\Tools\mingw1310_64\bin\gcc.exe'
OUT=ROOT/'tests/foc_current_zero_build/protected_loop.exe'
DEFINES=('FOC_PROTECTED_CLOSED_LOOP=1','FOC_CURRENT_TREND4=1','FOC_CURRENT_SPIKE_ONLY=1',
         'AS5047P_SPI_DMA=1','FOC_ADC_WINDOW=1','FOC_ADC_SENSE_TOPOLOGY=2')
class ProtectedLoopTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        OUT.parent.mkdir(exist_ok=True)
        cls.base=[GCC,'-std=c11','-O2','-Wall','-Wextra','-Werror','-pedantic','-UNDEBUG',
            '-I',str(ROOT/'firmware_common'),str(ROOT/'tests/protected_closed_loop_host.c'),
            str(ROOT/'firmware_common/foc_current_zero.c'),str(ROOT/'firmware_common/foc_zero_median.c')]
        subprocess.run(cls.base+['-D'+x for x in DEFINES]+['-o',str(OUT)],check=True)
    def test_actual_runtime_shutdown_admission_and_single_lease(self):
        for case in range(30):
            with self.subTest(case=case):
                p=subprocess.run([str(OUT),str(case)],capture_output=True,text=True)
                self.assertEqual(p.returncode,0,p.stdout+p.stderr)
    def test_priority_fix_preserves_shutdown_and_rejects_irq_drift(self):
        candidate=OUT.with_name('protected_loop_priority_fix.exe')
        subprocess.run(self.base+['-D'+x for x in DEFINES]+
            ['-DAS5047P_DMA_IRQ_PREEMPT_ADC=1','-o',str(candidate)],check=True)
        for case in range(31):
            with self.subTest(case=case):
                p=subprocess.run([str(candidate),str(case)],capture_output=True,text=True)
                self.assertEqual(p.returncode,0,p.stdout+p.stderr)
    def test_compile_rejects_diagnostic_bypasses_and_wrong_topology(self):
        base=self.base+['-fsyntax-only']
        for forbidden in ('FOC_ISOLATED_CONCURRENCY','FOC_FEEDBACK_SAFETY_BINDING',
                          'FOC_CONTROL_CHAIN_RECONNECT','FOC_RAW_OBSERVE_ONLY',
                          'FOC_FILTERED_OBSERVE_ONLY','ZERO_RETEST_BOOT','SAFETY_LOCKED_BOOT'):
            p=subprocess.run(base+['-D'+x for x in DEFINES]+['-D'+forbidden+'=1'],capture_output=True,text=True)
            self.assertNotEqual(p.returncode,0,forbidden)
        for topology in (0,1):
            p=subprocess.run(base+['-D'+x for x in DEFINES if not x.startswith('FOC_ADC_SENSE_TOPOLOGY=')]+
                ['-DFOC_ADC_SENSE_TOPOLOGY='+str(topology)],capture_output=True,text=True)
            self.assertNotEqual(p.returncode,0,topology)
    def test_ab_local_only_single_filter_fault_hooks_and_no_boot_enable(self):
        binding=(ROOT/'firmware_common/protected_closed_loop.inc').read_text('utf-8')
        self.assertNotIn('BootHealth_IsCurrentTrial(',binding)
        self.assertEqual(binding.count('BootMeta_ReadV3('),1)
        self.assertIn('boot.pending_slot==BOOT_SLOT_NONE',binding)
        self.assertIn('boot.attempts_left==0U',binding)
        for slot in 'ab':
            source=read_app_source(ROOT/f'foc2_app_{slot}/Core/Src/main.c','utf-8')
            self.assertIn('ProtectedLoop_TaskService();',source)
            self.assertIn('ProtectedLoop_Shutdown();',source)
            self.assertIn('#include "protected_adc_irq.inc"',source)
            self.assertIn('ProtectedLoop_SetDuty(du,dv,dw);',source)
            self.assertIn('ProtectedLoop_EmergencyOff(CL_BAD_ADC);',source)
            self.assertIn('ProtectedLoop_EmergencyOff(CL_BAD_ENCODER);',source)
            self.assertIn('ProtectedLoop_EmergencyOff(CL_CORE_FAULT);',source)
            protocol=source[source.index('else if (strncmp(cmd,"MOTOR TEST "'):]
            self.assertIn('protocol_reply_route_active || !protocol_esp_ping_uart_local',protocol[:400])
            fn=source[source.index('static void PWM_StartAll(void)\n{'):]
            self.assertIn('FOC_PROTECTED_CLOSED_LOOP',fn[:300])
            self.assertIn('return;',fn[:300])
            self.assertIn('cl_frame.measurement_angle',source)
            self.assertIn('cl_frame.actuation_angle',source)
            irq=(ROOT/f'foc2_app_{slot}/Core/Src/stm32g4xx_it.c').read_text('utf-8')
            self.assertIn('#define SWITCH_FAULT_OFF() ProtectedLoop_EmergencyOff(CL_CORE_FAULT)',irq)

if __name__=='__main__': unittest.main()
