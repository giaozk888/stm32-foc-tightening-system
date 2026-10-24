from pathlib import Path
import struct
import subprocess
import sys
import unittest
from test_torque_chain import GCC
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
import id_steady_report as report


class IdSteadyReportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        code=r'''
#include <stdio.h>
#include <io.h>
#include <fcntl.h>
#include "id_steady_stats.h"
static IdSteadyStats s;
int main(void){_setmode(_fileno(stdout),_O_BINARY);IdSteady_Lifecycle(&s,1,0);
for(unsigned i=0;i<1499;i++){
 unsigned enc=1000*(i+1);MechanicalCurrent c={2,20*(i+1),enc+115,enc+134,i<599?.08f:.01f,.22f,0};
 IdSteady_Observe(&s,enc+160,enc,1000,600,0,600,0,0,&c,1,i<549?.06f:.01f,8,0);
}
IdSteady_Lifecycle(&s,0,0);fwrite(&s,sizeof s,1,stdout);return 0;}
'''
        exe=ROOT/'tmp/id-steady-decoder-fixture.exe'
        p=subprocess.run([GCC,'-std=c11','-Os','-Wall','-Wextra','-Werror','-I',str(ROOT/'firmware_common'),
            str(ROOT/'firmware_common/id_steady_stats.c'),'-x','c','-','-o',str(exe)],input=code,text=True,capture_output=True)
        if p.returncode:raise AssertionError(p.stdout+p.stderr)
        p=subprocess.run([str(exe)],capture_output=True)
        if p.returncode:raise AssertionError(p.stderr)
        cls.raw=p.stdout

    def test_actual_c_abi_moments_duration_distributions_and_no_valid_selection(self):
        d=report.decode_bytes(self.raw)
        self.assertTrue(d['fixed_window_complete'] and d['steady_throughout'])
        self.assertEqual(d['meta']['good_us'],1000000)
        self.assertEqual(d['meta']['good_n'],1000)
        self.assertAlmostEqual(d['signals']['Id_meas_A']['mean'],.017,places=5)
        self.assertAlmostEqual(d['signals']['Id_ref_A']['max'],0)
        self.assertAlmostEqual(d['signals']['Iq_A']['mean'],.22,places=5)
        self.assertEqual(d['over_50ma']['raw_abs_Id']['total_ms'],100)
        self.assertEqual(d['over_50ma']['raw_abs_Id']['max_observed_run_ms'],100)
        self.assertEqual(d['over_50ma']['dob_filtered_abs_Id']['total_ms'],50)
        self.assertEqual(d['whole_run_dob_status_counts']['WARMUP'],1499)
        self.assertEqual(d['whole_run_dob_status_counts']['VALID'],0)
        self.assertFalse(d['feedback_enabled'] or d['threshold_changed'])

    def test_corrupt_counter_moments_histogram_and_open_run_fail_closed(self):
        for offset,value in ((0,1),(4,8),(32,1000001),(184,1000001),(188,1),(264,0)):
            data=bytearray(self.raw);struct.pack_into('<I',data,offset,value)
            with self.assertRaises(ValueError,msg=str(offset)):report.decode_bytes(data)
        data=bytearray(self.raw);struct.pack_into('<f',data,104,float('nan'))
        with self.assertRaises(ValueError):report.decode_bytes(data)
        with self.assertRaises(ValueError):report.decode_bytes(self.raw[:-1])


if __name__=='__main__':unittest.main()
