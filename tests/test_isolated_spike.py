"""Offline checks only; never accesses serial, debugger or a power output."""

from app_source_view import read_app_source
from pathlib import Path
import json
import math
import random
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]
GCC = r'D:\Qt\Tools\mingw1310_64\bin\gcc.exe'

class IsolatedSpikeTests(unittest.TestCase):
    def test_deterministic_random_and_bandlimited_waveforms(self):
        out = ROOT/'tests/foc_current_zero_build/spike_replay.exe'
        subprocess.run([GCC, '-std=c11', '-O2', '-Wall', '-Wextra', '-Werror',
                        '-DFOC_CURRENT_SPIKE_ONLY=1', '-I', str(ROOT/'firmware_common'),
                        str(ROOT/'tests/foc_current_spike_replay_host.c'),
                        '-o', str(out)], check=True)
        rng = random.Random(20261012)
        samples = [(rng.randrange(4096),rng.randrange(4096)) for _ in range(16000)]
        result = subprocess.run([str(out)],input=''.join(f'{u} {v}\n' for u,v in samples),
                                capture_output=True,text=True,check=True,timeout=10)
        rows = [tuple(map(int,line.split())) for line in result.stdout.splitlines()]
        self.assertEqual(len(rows),len(samples)-2)
        for index,u,v,mask in rows:
            for ch,value in enumerate((u,v)):
                a,b,c = [samples[i][ch] for i in (index-1,index,index+1)]
                isolated = abs(a-c)<=10 and abs(a-b)>40 and abs(b-c)>40 and (b>max(a,c) or b<min(a,c))
                self.assertEqual(bool(mask & (1<<ch)),isolated)
                self.assertEqual(value,(a+c+1)//2 if isolated else b)
        # Synthetic ideal waveforms, not an analog bandwidth/current claim.
        for hz in (20,100,500,1000):
            samples = [(round(1560+500*math.sin(2*math.pi*hz*n/20000)),1560)
                       for n in range(4000)]
            result = subprocess.run([str(out)],input=''.join(f'{u} {v}\n' for u,v in samples),
                                    capture_output=True,text=True,check=True,timeout=10)
            for index,u,v,mask in (tuple(map(int,s.split())) for s in result.stdout.splitlines()):
                self.assertEqual(mask,0,f'{hz}Hz center {index}')
                self.assertEqual((u,v),samples[index])
        # Known limitation retained as a regression: 1.3 kHz real sinusoidal
        # peaks can match the 10/40 rule. This is NOT full-band qualification.
        samples=[(round(1560+500*math.sin(2*math.pi*1300*n/20000)),1560) for n in range(4000)]
        result=subprocess.run([str(out)],input=''.join(f'{u} {v}\n' for u,v in samples),
                              capture_output=True,text=True,check=True,timeout=10)
        altered=[(index,u,mask) for index,u,v,mask in
                 (map(int,s.split()) for s in result.stdout.splitlines()) if u!=samples[index][0]]
        self.assertGreater(len(altered),0,'Do not claim high-frequency peaks are untouched')
        self.assertTrue(all(mask==1 for index,u,mask in altered))

    def test_saved_off_capture_replay(self):
        source = ROOT/'safety_backups/switch-feedback-20261012/off-repaired-a-1791801336398511500.json'
        samples = json.loads(source.read_text(encoding='utf-8'))['samples']
        out = ROOT/'tests/foc_current_zero_build/spike_replay.exe'
        out.parent.mkdir(exist_ok=True)
        subprocess.run([GCC, '-std=c11', '-O2', '-Wall', '-Wextra', '-Werror',
                        '-DFOC_CURRENT_SPIKE_ONLY=1', '-I', str(ROOT/'firmware_common'),
                        str(ROOT/'tests/foc_current_spike_replay_host.c'),
                        '-o', str(out)], check=True)
        result = subprocess.run([str(out)], input=''.join(f'{u} {v}\n' for u,v in samples),
                                capture_output=True, text=True, check=True, timeout=10)
        rows = [tuple(map(int,line.split())) for line in result.stdout.splitlines()]
        self.assertEqual(len(rows), len(samples)-2)
        for expected_index, (index, u, v, mask) in enumerate(rows,1):
            self.assertEqual(index, expected_index)
            for ch, value in enumerate((u,v)):
                a,b,c = (samples[index-1][ch],samples[index][ch],samples[index+1][ch])
                isolated = abs(a-c)<=10 and abs(a-b)>40 and abs(b-c)>40 and (b>max(a,c) or b<min(a,c))
                self.assertEqual(bool(mask & (1<<ch)), isolated)
                self.assertEqual(value, (a+c+1)//2 if isolated else b)

    def test_actual_compute_only_binding(self):
        from test_median_control_integration import MedianControlTests
        MedianControlTests().compile_run('spike_port',
            ['tests/foc_current_zero_port_host.c', 'firmware_common/foc_current_zero.c',
             'firmware_common/foc_zero_median.c'],
            ['-DFOC_ISOLATED_CONCURRENCY=1', '-DFOC_ZERO_MEDIAN_COMPUTE_ONLY=1',
             '-DFOC_CURRENT_SPIKE_ONLY=1'])

    def test_actual_c_algorithm_runtime_and_calibration(self):
        out = ROOT / 'tests/foc_current_zero_build/spike_host.exe'
        out.parent.mkdir(exist_ok=True)
        subprocess.run([GCC, '-std=c11', '-O2', '-Wall', '-Wextra', '-Werror',
                        '-pedantic', '-UNDEBUG', '-DFOC_CURRENT_SPIKE_ONLY=1',
                        '-I', str(ROOT/'firmware_common'),
                        str(ROOT/'tests/foc_current_spike_host.c'),
                        str(ROOT/'firmware_common/foc_current_zero.c'),
                        str(ROOT/'firmware_common/foc_zero_median.c'),
                        '-o', str(out)], check=True)
        result = subprocess.run([str(out)], capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('host PASS', result.stdout)

    def test_both_slots_and_locked_default(self):
        for slot in 'ab':
            src = read_app_source(ROOT/f'foc2_app_{slot}/Core/Src/main.c',encoding='utf-8')
            self.assertIn('#include "foc_current_spike_runtime.inc"', src)
            self.assertIn('FocCurrentMedian_Begin(&current_spike_filter)', src)
            cmake = (ROOT/f'foc2_app_{slot}/CMakeLists.txt').read_text()
            self.assertIn('output-locked profiles only" OFF)', cmake)
            self.assertIn('FOC_CURRENT_SPIKE_ONLY AND NOT ZERO_RETEST_BOOT AND NOT FOC_ISOLATED_CONCURRENCY', cmake)

if __name__ == '__main__':
    unittest.main()
