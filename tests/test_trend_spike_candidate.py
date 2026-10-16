"""Offline candidate tests only; no firmware binding or hardware access."""
from pathlib import Path
import json
import math
import random
import subprocess
import sys
import unittest
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
from compare_spike_candidates import select

class TrendCandidateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.exes={}
        for kind in ('quadratic4_30_40','cubic5_30_40'):
            out=ROOT/f'safety_backups/filter-comparison-20261012/{kind}.exe'
            out.parent.mkdir(exist_ok=True)
            args=[r'D:\Qt\Tools\mingw1310_64\bin\gcc.exe','-O2','-std=c11','-Wall','-Wextra','-Werror']
            if kind.startswith('quadratic4'): args+=['-DOFFLINE_QUADRATIC4=1']
            subprocess.run(args+[str(ROOT/'tests/foc_spike_cubic5_replay.c'),'-o',str(out)],check=True)
            cls.exes[kind]=out

    def replay(self,kind,samples):
        result=subprocess.run([str(self.exes[kind])],input=''.join(f'{u} {v}\n' for u,v in samples),
                              text=True,capture_output=True,check=True,timeout=10)
        return [tuple(map(int,line.split())) for line in result.stdout.splitlines()]

    def test_saved_raw_and_random_equivalence(self):
        saved=json.loads((ROOT/'safety_backups/switch-feedback-20261012/off-repaired-a-1791801336398511500.json').read_text('utf-8'))['samples']
        rng=random.Random(10712)
        for samples in (saved,[(rng.randrange(4096),rng.randrange(4096)) for _ in range(12000)]):
            for kind in self.exes:
                rows=self.replay(kind,samples)
                window=4 if kind.startswith('quadratic4') else 5
                self.assertEqual(len(rows),len(samples)-window+1)
                for rownum,(i,u,v,mask) in enumerate(rows):
                    self.assertEqual(i,rownum+2)
                    for ch,value in enumerate((u,v)):
                        neighbors=[samples[k][ch] for k in range(i-2,i+2)]
                        neighbors.append(samples[i+2][ch] if i+2<len(samples) else 0)
                        expected=select(neighbors,kind)
                        self.assertEqual(value,expected)
                        self.assertEqual(bool(mask&(1<<ch)),expected!=samples[i][ch])
                        if value!=samples[i][ch]:
                            self.assertGreaterEqual(value,min(samples[i-1][ch],samples[i+1][ch]))
                            self.assertLessEqual(value,max(samples[i-1][ch],samples[i+1][ch]))

    def test_sine_phase_amplitude_sweep(self):
        for amp in (500,1000,1500):
            for hz in (100,500,1000,1300):
                for phase in (0,.17,.51,1.03):
                    samples=[(round(2048+amp*math.sin(2*math.pi*hz*n/20000+phase)),2048) for n in range(1000)]
                    for kind in self.exes:
                        for i,u,v,mask in self.replay(kind,samples):
                            self.assertEqual((u,v,mask),(*samples[i],0),(kind,amp,hz,phase,i))

    def test_non_spike_shapes_and_outer_corruption(self):
        signals=[[1560]*20+[1900]*20,[1560]*20+[1900]*2+[1560]*20,
                 list(range(1200,2000,5)),[3000,1560,1562,1560,1560]]
        for kind in self.exes:
            for signal in signals:
                samples=[(x,1560) for x in signal]
                for i,u,v,mask in self.replay(kind,samples):
                    self.assertEqual((u,v,mask),(*samples[i],0))

    def test_one_period_quad_delay_and_real_pulse_ambiguity(self):
        # Exactly four arrivals emit center #2; no future fifth sample needed.
        samples=[(1560,1560),(1562,1560),(1621,1560),(1563,1560)]
        self.assertEqual(self.replay('quadratic4_30_40',samples),[(2,1563,1560,1)])
        self.assertEqual(self.replay('cubic5_30_40',samples),[])
        # A real physical one-sample pulse is also filtered: protection must
        # not infer that a rejected feedback point was necessarily EMI.
        for kind in self.exes:
            rows=self.replay(kind,[(1560,1560)]*10+[(2400,1560)]+[(1560,1560)]*10)
            self.assertEqual(next(row for row in rows if row[0]==10)[1:],(1560,1560,1))

if __name__=='__main__': unittest.main()
