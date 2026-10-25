"""Offline integration only. No debugger, serial, flashing, or motor commands."""

from app_source_view import read_app_source
import hashlib
import json
import re
import subprocess
import unittest
from pathlib import Path
import test_foc_irq_source_trace as prior
import test_foc_compact_closed_loop as compact

ROOT=Path(__file__).resolve().parents[1]
COMMON=ROOT/'firmware_common'
GCC=compact.GCC
FLAGS=prior.GATE+['-DFOC_RAM_HOT_PATH=1','-DFOC_IRQ_COMPACT=1','-DFOC_LATEST_ORIGINAL_FSM=1']
OUT=ROOT/'tests/foc_adaptive_build'
PRESET='LatestFeedbackOriginalFsm'

def run(*args):
    p=subprocess.run([str(x) for x in args],capture_output=True,text=True,timeout=30)
    if p.returncode:
        raise AssertionError(p.stdout+p.stderr)
    return p.stdout

class LatestOriginalTests(unittest.TestCase):
    def test_actual_irq_discards_shadow_but_keeps_running_integrators(self):
        for opt in ('-Os','-O2'):
            exe=OUT/('latest_original_irq'+opt+'.exe')
            run(GCC,'-std=c11',opt,'-Wall','-Wextra','-Werror','-pedantic','-UNDEBUG',
                '-I',COMMON,*FLAGS,ROOT/'tests/latest_original_irq_host.c','-o',exe)
            self.assertIn('PASS',run(exe))

    def test_actual_adapter_and_command_mailbox(self):
        OUT.mkdir(exist_ok=True)
        for opt in ('-Os','-O2'):
            exe=OUT/('latest_original'+opt+'.exe')
            run(GCC,'-std=c11',opt,'-Wall','-Wextra','-Werror','-pedantic','-UNDEBUG',
                '-I',COMMON,*FLAGS,ROOT/'tests/latest_original_fsm_host.c',
                COMMON/'foc_current_zero.c',COMMON/'foc_zero_median.c',
                COMMON/'foc_zero_robust.c','-o',exe)
            self.assertIn('PASS',run(exe))

    def test_partial_or_bypass_profile_rejected(self):
        for flags in (
            *([f for f in FLAGS if f!='-D'+drop+'=1'] for drop in
              ('FOC_PROTECTED_CLOSED_LOOP','FOC_RAM_HOT_PATH','FOC_IRQ_COMPACT','FOC_GATE_REUSE')),
            *(FLAGS+['-D'+flag+'=1'] for flag in
              ('FOC_ADAPTIVE_FILTER_EXPERIMENT','FOC_ZERO_TOTAL_BUDGET_OFF',
               'FOC_RAW_OBSERVE_ONLY','FOC_COMPACT_CLOSED_LOOP'))):
            p=subprocess.run([GCC,'-std=c11','-fsyntax-only','-I',str(COMMON),*flags,
                              str(ROOT/'tests/latest_original_fsm_host.c')],capture_output=True)
            self.assertNotEqual(p.returncode,0,flags)

    def test_old_fsm_switch_identical_in_both_slots_and_not_reimplemented(self):
        blocks=[]
        for slot in 'ab':
            source=read_app_source(ROOT/f'foc2_app_{slot}/Core/Src/main.c','utf-8')
            task=source[source.index('static void TighteningTask(void *argument)\n{'):]
            start=task.index('switch (tightening_test_stage)')
            end=task.index('LatestOriginal_FsmService();',start)
            blocks.append(task[start:end])
            for stage in ('RUNDOWN','CONTACT_STOP','SEATING','HOLD','DONE','FAULT'):
                self.assertIn('TIGHTEN_STATE_'+stage,blocks[-1])
            self.assertIn('else if (start_request_routed || !LatestOriginal_Admit())',task[:start])
            # START must set its real recipe, not the isolated MOTOR TEST speed.
            self.assertIn('(float)recipe_state.params.rundown_rpm',task[:start])
            self.assertIn('#include "latest_original_fsm.inc"',source)
        self.assertEqual(*blocks)
        adapter=(COMMON/'latest_original_fsm.inc').read_text('utf-8')
        self.assertNotIn('switch (',adapter)
        self.assertNotIn('MotorControl_SetSpeed(',adapter)
        self.assertNotIn('FOC_ResetController(',adapter)
        self.assertIn('!Tightening_IsBusy()',adapter)

    def test_shadow_pi_reset_brackets_real_current_step(self):
        irq=(COMMON/'protected_adc_irq.inc').read_text('utf-8')
        step=irq.index('FOC_CurrentLoopStep(')
        calls=[m.start() for m in re.finditer('FocCurrentPi_Reset',irq)]
        self.assertEqual(len(calls),2)
        self.assertLess(calls[0],step)
        self.assertGreater(calls[1],step)
        self.assertEqual(irq.count('if (cl_session.state!=CL_RUNNING) FocCurrentPi_Reset'),2)
        adapter=(COMMON/'latest_original_fsm.inc').read_text('utf-8')
        self.assertLess(adapter.index('FocCurrentPi_Reset'),adapter.index('TIM1->CCER=0x555U'))

    def test_linked_profile_kernel_limits_and_resource_budget(self):
        for slot in 'ab':
            folder=ROOT/f'foc2_app_{slot}/build/{PRESET}'
            data=(folder/'foc2.bin').read_bytes()
            for marker in (b'NAME=LATEST_ORIGINAL_FSM HARD_OFF=0 ADAPT=1 FSM=ORIGINAL',
                           b'ADAPT=1 HARD_OFF=0 DELAY_PAIRS=1',
                           b'RAM ENABLED=1 HARD_OFF=0 DEADLINE_US=50',
                           b'MAX=20 SEG_MAX=OFF',b'USE_ORIGINAL_START',
                           b'TIGHTEN: START -> RUNDOWN'):
                self.assertTrue(marker in data,(slot,marker))
            self.assertNotIn(b'NAME=COMPACT_CLOSED_LOOP',data)
            self.assertNotIn(b'MAX=OFF SEG_MAX=OFF',data)
            cache=(folder/'CMakeCache.txt').read_text('utf-8')
            for flag in ('FOC_LATEST_ORIGINAL_FSM','AS5047P_SPI_DMA','AS5047P_DMA_IRQ_PREEMPT_ADC',
                         'FOC_ADC_WINDOW','FOC_FAST_MATH','FOC_RAM_HOT_PATH','FOC_IRQ_COMPACT',
                         'FOC_PAIR_FAST_PATH','FOC_GUARD_FAST_PATH','FOC_FEEDBACK_FAST_PATH','FOC_GATE_REUSE'):
                self.assertIn(flag+':BOOL=ON',cache)
            for flag in ('FOC_ADAPTIVE_FILTER_EXPERIMENT','FOC_ZERO_TOTAL_BUDGET_OFF',
                         'FOC_ORIGINAL_CLOSED_LOOP_UPDATED','FOC_COMPACT_CLOSED_LOOP'):
                self.assertIn(flag+':BOOL=OFF',cache)
            self.assertLess(len(data),224*1024)
            mapping=(folder/'foc2.map').read_text('utf-8')
            end=re.search(r'^\._user_heap_stack\s*\n\s*0x([a-f0-9]+)\s+0x([a-f0-9]+)',mapping,re.M)
            used=sum(int(x,16) for x in end.groups())-0x20000000
            self.assertGreaterEqual(0x1ffc0-used,8192)
            print(slot,len(data),hashlib.sha256(data).hexdigest(),'RAM_HEADROOM',0x1ffc0-used)

    def test_actual_linked_guard_is_integer_only(self):
        case=compact.CompactClosedLoopTests('test_actual_guardian_linked_integer_only')
        case.ELF_PRESET=PRESET
        case.test_actual_guardian_linked_integer_only()

if __name__=='__main__': unittest.main()
