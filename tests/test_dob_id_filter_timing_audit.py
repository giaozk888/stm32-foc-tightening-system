import csv
import io
from pathlib import Path
import subprocess
import unittest
from test_torque_chain import GCC
ROOT=Path(__file__).resolve().parents[1]


class IdFilterTimingAuditTests(unittest.TestCase):
    def test_actual_c_waveform_filter_gate_same_epoch_and_recovery_not_20ms(self):
        for opt in ('-Os','-O2'):
            exe=ROOT/'tmp'/('dob-id-filter-audit'+opt+'.exe')
            p=subprocess.run([GCC,'-std=c11',opt,'-Wall','-Wextra','-Werror',
                '-I',str(ROOT/'firmware_common'),str(ROOT/'tests/dob_id_filter_timing_audit_host.c'),
                str(ROOT/'firmware_common/mechanical_dob_monitor.c'),
                str(ROOT/'firmware_common/id_steady_stats.c'),'-o',str(exe)],capture_output=True,text=True)
            self.assertEqual(p.returncode,0,p.stdout+p.stderr)
            p=subprocess.run([str(exe)],capture_output=True,text=True)
            self.assertEqual(p.returncode,0,p.stdout+p.stderr)
            groups={}
            for row in csv.DictReader(io.StringIO(p.stdout)):
                groups.setdefault(row['case'],[]).append(row)
            rows=groups['bipolar_60mA']
            self.assertTrue(all(r['status']=='256' and r['valid']=='0' for r in rows))
            self.assertAlmostEqual(float(rows[-1]['filtered_abs_A']),.06,places=6)
            self.assertLess(abs(float(rows[-1]['signed_lpf_A'])),.002)
            rows=groups['one_pulse_base40mA']
            self.assertAlmostEqual(float(rows[800]['filtered_abs_A']),.0523809524,places=6)
            self.assertEqual([i for i,r in enumerate(rows) if r['status']=='256'],list(range(800,805)))
            self.assertEqual(rows[805]['warmup_us'],'0')
            self.assertEqual(next(i for i in range(805,2000) if rows[i]['valid']=='1'),1203)
            self.assertEqual(int(rows[-1]['stats_filtered_total_us']),5000)
            rows=groups['one_pulse_base10mA']
            self.assertFalse(any(r['status']=='256' for r in rows))
            self.assertEqual(rows[800]['valid'],'1')
            rows=groups['repeated_pulses_60ms']
            self.assertFalse(any(r['valid']=='1' for r in rows[800:1521]))
            rows=groups['quality_gap_reseed']
            self.assertEqual(rows[800]['have_sample'],'0')
            self.assertAlmostEqual(float(rows[801]['filtered_abs_A']),.08,places=6)
            rows=groups['threshold_equal']
            self.assertFalse(any(r['status']=='256' for r in rows))
            self.assertEqual(rows[-1]['valid'],'1')
            self.assertTrue(any(r['status']=='256' for r in groups['jitter_dt']))


if __name__=='__main__':unittest.main()
