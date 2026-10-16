"""Production C replay, synthetic truth, and hard-off binding; NO board access."""
import json
import math
from pathlib import Path
import random
import re
import subprocess
import unittest
import test_foc_irq_source_trace as prior

ROOT=prior.ROOT
GCC=prior.feedback.guard.pair.binding.GCC
OUT=ROOT/'tests/foc_adaptive_build'
BASE=['-DFOC_PROTECTED_CLOSED_LOOP=1','-DFOC_CURRENT_TREND4=1','-DFOC_CURRENT_SPIKE_ONLY=1']
ADAPT=BASE+['-DFOC_ADAPTIVE_FILTER_EXPERIMENT=1']

def compile_replays():
    OUT.mkdir(exist_ok=True)
    result={}
    for name,flags in [('fixed',BASE),('adaptive',ADAPT),
                       ('adaptive_no_quota',ADAPT+['-DFOC_ZERO_TOTAL_BUDGET_OFF=1'])]:
        exe=OUT/(name+'.exe')
        subprocess.run([GCC,'-std=c11','-O2','-Wall','-Wextra','-Werror','-pedantic',
            '-UNDEBUG','-I',str(ROOT/'firmware_common'),*flags,
            str(ROOT/'tests/foc_adaptive_replay.c'),str(ROOT/'firmware_common/foc_zero_median.c'),
            str(ROOT/'firmware_common/foc_zero_robust.c'),str(ROOT/'firmware_common/foc_current_zero.c'),
            '-o',str(exe)],check=True)
        result[name]=exe
    return result

def replay(exe,samples,mode=None):
    p=subprocess.run([str(exe)]+([mode] if mode else []),
        input=''.join(f'{u} {v}\n' for u,v in samples),text=True,capture_output=True,check=True)
    return json.loads(p.stdout) if mode else [tuple(map(int,x.split())) for x in p.stdout.splitlines()]

class AdaptiveFilterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.exes=compile_replays()

    def test_bounds_and_median_network(self):
        exe=OUT/'unit.exe'
        subprocess.run([GCC,'-O2','-std=c11','-Wall','-Wextra','-Werror','-pedantic','-UNDEBUG',
            '-I',str(ROOT/'firmware_common'),str(ROOT/'tests/foc_adaptive_unit.c'),
            str(ROOT/'firmware_common/foc_zero_robust.c'),str(ROOT/'firmware_common/foc_current_zero.c'),
            '-o',str(exe)],check=True)
        subprocess.run([str(exe)],check=True)

    def test_fixed_unchanged_and_smaller_isolated_spikes(self):
        for amplitude in (20,25,35,41,300):
            samples=[(1560,1560)]*80+[(1560+amplitude,1560)]+[(1560,1560)]*80
            rows={k:replay(e,samples) for k,e in self.exes.items()}
            self.assertEqual(rows['fixed'][78][1],1560 if amplitude>40 else 1560+amplitude)
            self.assertEqual(rows['adaptive'][78][1],1560 if amplitude>20 else 1560+amplitude)
            self.assertEqual([x[0] for x in rows['adaptive']],list(range(2,len(samples)-1)))

    def test_steps_ramps_and_two_sample_real_pulses_unchanged(self):
        signals=[[1560]*40+[1900]*80,[1560]*40+[1900]*2+[1560]*80,
                 list(range(1200,2400,5)),[1560]*40+[1600]*2+[1560]*40]
        for values in signals:
            samples=[(x,1560) for x in values]
            for i,u,v,mask in replay(self.exes['adaptive'],samples):
                self.assertEqual((u,v,mask),(*samples[i],0))

    def test_sine_sweep_has_no_extra_repairs(self):
        for amplitude in (100,500,1000,1500):
            for hz in (100,500,1000,1300):
                for phase in (0,.17,.51,1.03):
                    samples=[(round(2048+amplitude*math.sin(2*math.pi*hz*n/20000+phase)),2048) for n in range(1000)]
                    for i,u,v,mask in replay(self.exes['adaptive'],samples):
                        self.assertEqual((u,v,mask),(*samples[i],0),(amplitude,hz,phase,i))

    def test_invalid_input_never_repaired_to_valid_and_output_range(self):
        rng=random.Random(20261014)
        samples=[(rng.randrange(4096),rng.randrange(4096)) for _ in range(15000)]
        samples[100]=(65535,5000)
        for i,u,v,mask in replay(self.exes['adaptive'],samples):
            if mask&1: self.assertTrue(min(samples[i-1][0],samples[i+1][0])<=u<=max(samples[i-1][0],samples[i+1][0]))
            if mask&2: self.assertTrue(min(samples[i-1][1],samples[i+1][1])<=v<=max(samples[i-1][1],samples[i+1][1]))
            if i==100: self.assertEqual((u,v,mask),(65535,5000,0))

    def zero(self,values): return replay(self.exes['adaptive'],[(1560,1560)]*20000+values,'--zero')

    def test_robust_zero_stable_and_sparse_outliers(self):
        values=[(1560+n%3-1,1560) for n in range(4000)]
        for n in range(100,4000,500): values[n]=(1800,1560)
        z=self.zero(values)
        self.assertEqual((z['state'],z['count'],z['segments'],z['outliers']),(3,4000,8,8))
        self.assertEqual(z['zero'],[1560,1560])
        self.assertEqual((z['raw_state'],z['raw_reason']),(4,2))

    def test_robust_zero_dense_burst_shift_drift_and_adc_invalid_fail(self):
        cases={
            'burst':[(1900 if n in (101,102) else 1560,1560) for n in range(4000)],
            'dense':[(1900 if n%50==0 else 1560,1560) for n in range(4000)],
            'shift':[(1800,1800)]*4000,
            'drift':[(1560+n//500,1560) for n in range(4000)],
            'invalid':[(1560,1560)]*100+[(5000,1560)]+[(1560,1560)]*3900,
            'unstable':[(1560+(35 if n%2 else -35),1560) for n in range(4000)],
        }
        for name,values in cases.items():
            z=self.zero(values)
            self.assertEqual((z['state'],z['zero']),(4,[0,0]),(name,z))
            flags={'burst':4,'dense':8,'shift':2,'drift':128,'invalid':1,'unstable':4}
            self.assertTrue(z['robust_flags']&flags[name],(name,z))

    def test_clustered_outliers_no_segment_cap_but_total_cap_retained(self):
        for count in (4,7,20,21):
            values=[(1560,1560)]*4000
            # All outliers are within the first 500 pairs, each in a
            # separate five-pair block; both channels still count as ONE pair.
            for n in range(count): values[10+n*10]=(1800,1800)
            z=self.zero(values)
            self.assertEqual(z['outliers'],count)
            self.assertEqual(z['state'],3 if count<=20 else 4)
            self.assertEqual(z['robust_flags'],0 if count<=20 else 8)
            self.assertEqual(z['zero'],[1560,1560] if count<=20 else [0,0])
            if count<=20:
                self.assertEqual((z['count'],z['segments']),(4000,8))

    def test_hard_off_no_total_quota_still_checks_bursts_and_drift(self):
        exe=self.exes['adaptive_no_quota']
        values=[(1560,1560)]*4000
        for n in range(80): values[10+n*50]=(1800,1800)
        z=replay(exe,[(1560,1560)]*20000+values,'--zero')
        self.assertEqual((z['state'],z['count'],z['segments'],z['outliers'],
                          z['robust_flags'],z['zero']),(3,4000,8,80,0,[1560,1560]))
        burst=[(1560,1560)]*4000
        burst[101]=burst[102]=(1800,1560)
        z=replay(exe,[(1560,1560)]*20000+burst,'--zero')
        self.assertEqual(z['state'],4)
        self.assertTrue(z['robust_flags']&4)
        drift=[(1560+n//500,1560) for n in range(4000)]
        z=replay(exe,[(1560,1560)]*20000+drift,'--zero')
        self.assertEqual(z['state'],4)
        self.assertTrue(z['robust_flags']&128)

    def test_outlier_distance_boundary_is_unchanged(self):
        for delta in (40,41):
            values=[(1560,1560)]*4000
            values[100]=(1560+delta,1560)
            z=self.zero(values)
            self.assertEqual((z['state'],z['zero']),(3,[1560,1560]))
            self.assertEqual(z['outliers'],0 if delta==40 else 1)

    def test_zero_budget_boundaries_and_no_partial_publication(self):
        for count in (20,21):
            values=[(1560,1560)]*4000
            for n in range(count): values[(n//3)*500+100+(n%3)*20]=(1800,1560)
            z=self.zero(values)
            self.assertEqual(z['state'],3 if count==20 else 4)
            self.assertEqual(z['zero'],[1560,1560] if count==20 else [0,0])
        partial=self.zero([(1560,1560)]*3999)
        self.assertEqual((partial['state'],partial['zero']),(2,[0,0]))

    def test_real_one_period_pulse_is_explicitly_ambiguous(self):
        samples=[(1560,1560)]*40+[(2400,1560)]+[(1560,1560)]*40
        self.assertEqual(next(x for x in replay(self.exes['adaptive'],samples) if x[0]==40),
                         (40,1560,1560,1))

    def test_actual_binding_hard_off(self):
        for mode,extra in (('binding',[]),('binding_no_quota',['-DFOC_ZERO_TOTAL_BUDGET_OFF=1'])):
            exe=OUT/(mode+'.exe')
            subprocess.run([GCC,'-std=c11','-O2','-Wall','-Wextra','-Werror','-pedantic','-UNDEBUG',
                '-I',str(ROOT/'firmware_common'),*prior.GATE,'-DFOC_ADAPTIVE_FILTER_EXPERIMENT=1',
                *extra,str(ROOT/'tests/foc_adaptive_binding_host.c'),str(ROOT/'firmware_common/foc_current_zero.c'),
                str(ROOT/'firmware_common/foc_zero_median.c'),str(ROOT/'firmware_common/foc_zero_robust.c'),
                '-o',str(exe)],check=True)
            subprocess.run([str(exe)],check=True)

    def test_actual_feedback_preserves_protection_and_alignment(self):
        exe=OUT/'safety.exe'
        subprocess.run([GCC,'-std=c11','-O2','-Wall','-Wextra','-Werror','-pedantic','-UNDEBUG',
            '-I',str(ROOT/'firmware_common'),*prior.GATE,'-DFOC_ADAPTIVE_FILTER_EXPERIMENT=1',
            str(ROOT/'tests/foc_adaptive_safety_host.c'),'-o',str(exe)],check=True)
        subprocess.run([str(exe)],check=True)

    def test_linked_guardian_remains_integer_only(self):
        arm=prior.feedback.guard.ARM
        for slot in 'ab':
            elf=ROOT/f'foc2_app_{slot}/build/ProtectedAdaptiveFilter/foc2.elf'
            disasm=subprocess.run([str(arm/'arm-none-eabi-objdump.exe'),'-d',str(elf)],
                capture_output=True,text=True,check=True).stdout
            blocks={m.group(1):m.group(2) for m in re.finditer(
                r'^[0-9a-f]+ <([^>]+)>:\n(.*?)(?=^[0-9a-f]+ <|\Z)',disasm,re.M|re.S)}
            seen=set(); pending=['TIM7_DAC_IRQHandler']
            while pending:
                symbol=pending.pop()
                if symbol in seen: continue
                seen.add(symbol); body=blocks[symbol]
                self.assertNotRegex(body,r'\t(?:v[a-z][a-z0-9]*)(?:\.[a-z0-9]+)?\s')
                self.assertNotIn('<__aeabi_',body); self.assertNotIn('<memcpy>',body)
                self.assertNotRegex(body,r'\t(?:blx|bx)\s+r[0-9]+\b')
                pending.extend(re.findall(r'\t(?:bl|blx|b(?:\.[wn])?)\s+[^<\n]*<([^+>]+)>',body))
            self.assertTrue({'ProtectedLoop_EmergencyOff','ProtectedLoop_Stop'}<=seen)

    def test_arm_selector_has_no_heap_fp_or_division_helpers(self):
        arm=prior.feedback.guard.ARM
        obj=OUT/'adaptive_arm.o'
        subprocess.run([str(arm/'arm-none-eabi-gcc.exe'),'-std=c11','-Os','-Wall','-Wextra','-Werror',
            '-mcpu=cortex-m4','-mfloat-abi=hard','-mfpu=fpv4-sp-d16','-fstack-usage',
            '-I',str(ROOT/'firmware_common'),*prior.GATE,'-DFOC_ADAPTIVE_FILTER_EXPERIMENT=1',
            '-c',str(ROOT/'tests/foc_adaptive_arm_probe.c'),'-o',str(obj)],check=True)
        symbols=subprocess.run([str(arm/'arm-none-eabi-nm.exe'),'-u',str(obj)],
            capture_output=True,text=True,check=True).stdout
        self.assertEqual(symbols.strip(),'')
        asm=subprocess.run([str(arm/'arm-none-eabi-objdump.exe'),'-d',str(obj)],
            capture_output=True,text=True,check=True).stdout
        self.assertNotRegex(asm,r'\t(?:v[a-z][a-z0-9]*)(?:\.[a-z0-9]+)?\s')
        self.assertNotRegex(asm,r'\t(?:bl|blx)\s+')

    def test_profiles_default_off_and_guard(self):
        for slot in 'ab':
            presets=json.loads((ROOT/f'foc2_app_{slot}/CMakePresets.json').read_text('utf-8'))
            p=next(x for x in presets['configurePresets'] if x['name']=='ProtectedAdaptiveFilter')
            self.assertEqual(p['inherits'],'ProtectedGateReuse')
            self.assertEqual(p['cacheVariables'],{'FOC_ADAPTIVE_FILTER_EXPERIMENT':'ON'})
            q=next(x for x in presets['configurePresets'] if x['name']=='ProtectedAdaptiveNoZeroQuota')
            self.assertEqual(q['inherits'],'ProtectedAdaptiveFilter')
            self.assertEqual(q['cacheVariables'],{'FOC_ZERO_TOTAL_BUDGET_OFF':'ON'})
        result=subprocess.run([GCC,'-fsyntax-only','-I',str(ROOT/'firmware_common'),
            '-DFOC_ADAPTIVE_FILTER_EXPERIMENT=1',str(ROOT/'tests/foc_adaptive_replay.c')],capture_output=True)
        self.assertNotEqual(result.returncode,0)

if __name__=='__main__': unittest.main()
