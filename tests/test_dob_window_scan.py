from pathlib import Path
import subprocess
import unittest
from test_torque_chain import GCC
ROOT=Path(__file__).resolve().parents[1]
GEN=ROOT/'simulation/dob_simulink/window_scan_work/generated'
class WindowTests(unittest.TestCase):
    def test_actual_float_classifier_baseline_identical_and_short_windows_still_detect(self):
        results={}
        for w in (0,100,75,50,30):
            stem=ROOT/'tmp'/('dob-window-native-'+str(w));include=ROOT/'firmware_common' if not w else GEN
            source=include/'dob_trend_shadow.c'
            flags=[] if not w else ['-DDOB_WINDOW_POINTS='+str(w)+'U',
                '-DDOB_WINDOW_MIN_GOOD='+str(w*6//10)+'U','-DDOB_WINDOW_MIN_SPAN_US='+str(w*600)+'U']
            p=subprocess.run([GCC,'-std=c11','-O2','-Wall','-Wextra','-Werror',*flags,'-I',str(include),
                str(ROOT/'tests/dob_window_scan_host.c'),str(source),'-lm','-o',str(stem)+'.exe'],capture_output=True,text=True)
            self.assertEqual(p.returncode,0,p.stderr)
            p=subprocess.run([str(stem)+'.exe',str(stem)+'.bin'],capture_output=True,text=True)
            self.assertEqual(p.returncode,0,p.stdout+p.stderr)
            results[w]=Path(str(stem)+'.bin').read_bytes()
        self.assertEqual(results[0],results[100],'100 ms generated baseline drift')
    def test_generated_changes_only_three_window_expressions_and_header_capacity(self):
        frozen=ROOT/'simulation/dob_simulink/window_scan_results/20261024_154439/firmware_sources'
        old=(frozen/'dob_trend_shadow.c').read_text();new=(GEN/'dob_trend_shadow.c').read_text()
        for a,b in {'span<60000U':'span<DOB_WINDOW_MIN_SPAN_US','n<60U':'n<DOB_WINDOW_MIN_GOOD',
                    '(float)n*.01f':'(float)n*(1.f/(float)DTS_WINDOW)'}.items():old=old.replace(a,b)
        self.assertEqual(old,new)
        self.assertTrue((GEN/'dob_trend_shadow.h').read_text().endswith(
            (ROOT/'firmware_common/dob_trend_shadow.h').read_text().replace(
            '#define DTS_WINDOW 100U','#define DTS_WINDOW DOB_WINDOW_POINTS')))
if __name__=='__main__':unittest.main()
