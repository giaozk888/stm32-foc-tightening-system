"""Bit-exact optimization checks against the frozen 2026-10-14 selector."""
import json
import subprocess
import unittest
import test_foc_adaptive_filter as adaptive

ROOT=adaptive.ROOT
OUT=adaptive.OUT
FLAGS=adaptive.prior.GATE+['-DFOC_ADAPTIVE_FILTER_EXPERIMENT=1']

def compile_comparison():
    OUT.mkdir(exist_ok=True)
    exes={}
    for name,extra in [('before',['-DFOC_ADAPTIVE_REFERENCE=1']),('after',[])]:
        exe=OUT/f'optimized_{name}.exe'
        subprocess.run([adaptive.GCC,'-std=c11','-O2','-Wall','-Wextra','-Werror',
            '-pedantic','-UNDEBUG','-I',str(ROOT/'firmware_common'),*FLAGS,*extra,
            str(ROOT/'tests/foc_adaptive_replay.c'),str(ROOT/'firmware_common/foc_zero_median.c'),
            str(ROOT/'firmware_common/foc_zero_robust.c'),str(ROOT/'firmware_common/foc_current_zero.c'),
            '-o',str(exe)],check=True)
        exes[name]=exe
    return exes

def saved_inputs():
    source=ROOT/'safety_backups/switch-feedback-20261012/off-repaired-a-1791801336398511500.json'
    yield source,json.loads(source.read_text('utf-8'))['samples']
    path=ROOT/'safety_backups/zero-failure-trace-20261012/sample-1791810619307161800.json'
    points=json.loads(path.read_text('utf-8'))['points']
    assert all(b['seq']==a['seq']+1 and b['a']==a['b'] and b['b']==a['c']
               for a,b in zip(points,points[1:]))
    yield path,[points[0]['a']]+[p['b'] for p in points]+[points[-1]['c']]

class OptimizedAdaptiveTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.exes=compile_comparison()

    def test_complete_pair_and_estimator_state_equivalence(self):
        for opt in ('-Os','-O2'):
            exe=OUT/('equivalence'+opt+'.exe')
            subprocess.run([adaptive.GCC,'-std=c11',opt,'-Wall','-Wextra','-Werror',
                '-pedantic','-UNDEBUG','-I',str(ROOT/'firmware_common'),*FLAGS,
                str(ROOT/'tests/foc_adaptive_equivalence.c'),'-o',str(exe)],check=True)
            subprocess.run([str(exe)],check=True)

    def test_saved_capture_outputs_and_full_learning_state_identical(self):
        for path,samples in saved_inputs():
            for mode in ('--state','--zero-window'):
                rows=[adaptive.replay(exe,samples,mode) if mode=='--zero-window' else
                    subprocess.run([str(exe),mode],input=''.join(f'{u} {v}\n' for u,v in samples),
                        capture_output=True,text=True,check=True).stdout
                    for exe in self.exes.values()]
                self.assertEqual(rows[0],rows[1],(str(path),mode))

    def test_benchmark_output_digest_identical(self):
        values=[json.loads(subprocess.run([str(exe),'--bench'],capture_output=True,
            text=True,check=True).stdout) for exe in self.exes.values()]
        self.assertEqual(values[0]['digest'],values[1]['digest'])

if __name__=='__main__': unittest.main()
