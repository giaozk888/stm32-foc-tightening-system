"""Separate motor-capable profile: actual mock runtime + linked ELF, no I/O."""
import hashlib
import json
import re
import subprocess
import unittest
import test_foc_irq_source_trace as prior

ROOT=prior.ROOT
GCC=prior.feedback.guard.pair.binding.GCC
ARM=prior.feedback.guard.ARM
FLAGS=prior.GATE+['-DFOC_RAM_HOT_PATH=1','-DFOC_IRQ_COMPACT=1','-DFOC_COMPACT_CLOSED_LOOP=1']
OUT=ROOT/'tests/foc_adaptive_build'
COMMON=ROOT/'firmware_common'

def run(*args):
    return subprocess.run([str(a) for a in args],check=True,capture_output=True,text=True).stdout

def build(name,source,flags=FLAGS,opt='-O2'):
    OUT.mkdir(exist_ok=True)
    exe=OUT/(name+'.exe')
    run(GCC,'-std=c11',opt,'-Wall','-Wextra','-Werror','-pedantic','-UNDEBUG',
        '-I',COMMON,*flags,ROOT/'tests'/source,COMMON/'foc_current_zero.c',
        COMMON/'foc_zero_median.c','-o',exe)
    return exe

class CompactClosedLoopTests(unittest.TestCase):
    ELF_PRESET='ProtectedCompactClosedLoop'

    def test_all_44_actual_binding_cases_same_as_original_protected(self):
        for opt in ('-Os','-O2'):
            ref=build('compact_motor_ref_'+opt,'protected_closed_loop_host.c',prior.GATE,opt)
            new=build('compact_motor_new_'+opt,'protected_closed_loop_host.c',FLAGS,opt)
            for case in range(44):
                self.assertEqual(run(ref,case),run(new,case),f'{opt} case {case}')

    def test_identity_break_refresh_and_zero_fail_closed(self):
        for opt in ('-Os','-O2'):
            exe=build('compact_motor_identity_'+opt,'foc_compact_closed_loop_host.c',opt=opt)
            self.assertIn('PASS',run(exe))

    def test_actual_adc_and_feedback_digest_unchanged(self):
        self.assertIn('PASS',run(build('compact_motor_adc','protected_adc_irq_host.c')))
        self.assertEqual(run(build('compact_motor_digest_ref','foc_pair_fast_host.c',prior.GATE)),
                         run(build('compact_motor_digest_new','foc_pair_fast_host.c')))

    def test_reject_partial_profiles_and_experiment_bypasses(self):
        for drop in ('FOC_PROTECTED_CLOSED_LOOP','FOC_RAM_HOT_PATH','FOC_IRQ_COMPACT',
                     'FOC_GATE_REUSE','FOC_FEEDBACK_FAST_PATH','FOC_GUARD_FAST_PATH'):
            flags=[f for f in FLAGS if f!='-D'+drop+'=1']
            p=subprocess.run([GCC,'-std=c11','-fsyntax-only','-I',str(COMMON),*flags,
                              str(ROOT/'tests/protected_closed_loop_host.c')],capture_output=True)
            self.assertNotEqual(p.returncode,0,drop)
        for forbidden in ('FOC_ADAPTIVE_FILTER_EXPERIMENT','FOC_ZERO_TOTAL_BUDGET_OFF',
                          'FOC_IRQ_SOURCE_TRACE','FOC_RAW_OBSERVE_ONLY','FOC_FILTERED_OBSERVE_ONLY',
                          'FOC_ISOLATED_CONCURRENCY','FOC_CONTROL_CHAIN_RECONNECT'):
            p=subprocess.run([GCC,'-std=c11','-fsyntax-only','-I',str(COMMON),*FLAGS,
                              '-D'+forbidden+'=1',str(ROOT/'tests/protected_closed_loop_host.c')],
                             capture_output=True)
            self.assertNotEqual(p.returncode,0,forbidden)

    def test_separate_opt_in_presets_and_old_hard_off_bins_unchanged(self):
        pins={'a':'266346496ccd788b6d5f7391c59bde23d2fd3d142801899f34473ee975d1de52',
              'b':'46eb9b65e0494a0fccac3dfd1c4b0935f3882c73e53bfb2f1c9cb2b3e270af73'}
        for slot,sha in pins.items():
            base=ROOT/f'foc2_app_{slot}'
            p=next(p for p in json.loads((base/'CMakePresets.json').read_text('utf-8'))
                   ['configurePresets'] if p['name']==self.ELF_PRESET)
            self.assertEqual(p['inherits'],'ProtectedGateReuse')
            self.assertEqual(p['cacheVariables'],{'FOC_COMPACT_CLOSED_LOOP':'ON',
                'FOC_RAM_HOT_PATH':'ON','FOC_IRQ_COMPACT':'ON'})
            self.assertEqual(hashlib.sha256((base/'build/ProtectedIrqCompact/foc2.bin').read_bytes()).hexdigest(),sha)

    def test_actual_guardian_linked_integer_only(self):
        # Compact intentionally removes the outlined Health/GatesMatch helpers.
        # Walk every actual linked target instead of requiring old symbol names.
        for slot in 'ab':
            elf=ROOT/f'foc2_app_{slot}/build/{self.ELF_PRESET}/foc2.elf'
            asm=run(ARM/'arm-none-eabi-objdump.exe','-d',elf)
            blocks={m[1]:m[2] for m in re.finditer(
                r'^[0-9a-f]+ <([^>]+)>:\n(.*?)(?=^[0-9a-f]+ <|\Z)',asm,re.M|re.S)}
            pending=['TIM7_DAC_IRQHandler']; seen=set()
            while pending:
                name=pending.pop()
                if name in seen: continue
                seen.add(name); self.assertIn(name,blocks)
                body=blocks[name]
                self.assertFalse(name.endswith('_veneer'),name)
                self.assertNotRegex(body,r'\t(?:v[a-z][a-z0-9]*)(?:\.[a-z0-9]+)?\s',name)
                self.assertNotRegex(body,r'\t(?:blx|bx)\s+r[0-9]+\b',name)
                self.assertNotRegex(body,r'<(?:memcpy|__aeabi_|HAL_Delay|malloc)')
                pending.extend(re.findall(r'\t(?:bl|blx|b(?:\.[wn])?)\s+[^<\n]*<([^+>]+)>',body))
            self.assertIn('ProtectedLoop_EmergencyOff',seen)
            self.assertIn('FocFeedbackGuard_OutputOff',seen)
            self.assertIn('FocIrqLoad_Enter',seen)
            print(f'PASS {slot} compact motor integer guardian: {len(seen)} linked functions')

    def test_linked_sram_running_duty_and_real_profile(self):
        for slot in 'ab':
            folder=ROOT/f'foc2_app_{slot}/build/{self.ELF_PRESET}'
            data=(folder/'foc2.bin').read_bytes()
            self.assertIn(b'NAME=COMPACT_CLOSED_LOOP HARD_OFF=0 ADAPT=0 ZERO=BOUNDED',data)
            self.assertIn(b'RAM ENABLED=1 HARD_OFF=0 DEADLINE_US=50',data)
            self.assertIn(b'COMPACT ENABLED=1 HARD_OFF=0 FIXED_OPS=1 GUARD_US=25 DEADLINE_US=50',data)
            self.assertNotIn(b'HARD_OFF=1',data)
            self.assertNotIn(b'MAX=OFF SEG_MAX=OFF',data)
            self.assertIn(b'FILTER=TREND4 OC=2_OF_3 TRIP_MA=4000',data)
            syms=run(ARM/'arm-none-eabi-nm.exe','-S',folder/'foc2.elf')
            table={m[3]:int(m[0],16) for line in syms.splitlines() if len(m:=line.split())==4}
            for name in ('ProtectedLoop_AdcIrq','TIM7_DAC_IRQHandler','TIM2_IRQHandler',
                         'DMA1_Channel4_IRQHandler','AsDma_Guard','AsDma_Begin'):
                self.assertTrue(0x20000000<=table[name]<0x20010000,(slot,name))
            self.assertNotIn('ops',table)
            mapping=(folder/'foc2.map').read_text('utf-8')
            end=re.search(r'^\._user_heap_stack\s*\n\s*0x([a-f0-9]+)\s+0x([a-f0-9]+)',mapping,re.M)
            used=sum(int(x,16) for x in end.groups())-0x20000000
            self.assertGreaterEqual(0x1ffc0-used,8*1024)
            self.assertLessEqual(len(data),224*1024)
            cache=(folder/'CMakeCache.txt').read_text('utf-8')
            self.assertIn('FOC_COMPACT_CLOSED_LOOP:BOOL=ON',cache)
            for flag in ('FOC_ADAPTIVE_FILTER_EXPERIMENT','FOC_ZERO_TOTAL_BUDGET_OFF',
                         'FOC_RAW_OBSERVE_ONLY','FOC_FILTERED_OBSERVE_ONLY'):
                self.assertIn(flag+':BOOL=OFF',cache)

if __name__=='__main__': unittest.main()
