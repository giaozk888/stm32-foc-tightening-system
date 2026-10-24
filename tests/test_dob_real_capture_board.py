import copy
import json
from pathlib import Path
import struct
import sys
import unittest
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
import dob_real_capture_board as b

class RealCaptureBoardTests(unittest.TestCase):
    def test_frozen_candidate_and_exact_original_restore_files_only(self):
        self.assertEqual(len(b.image()),223692)
        self.assertTrue(json.loads(b.BASELINE.read_text())['pass_'])
    def test_missing_physical_gates_prevent_even_configure(self):
        for args in [['--stage-off'],['--execute-five','missing'],['--restore-b-drive-off','missing']]:
            with patch.object(b,'configure') as configure:
                with self.assertRaises(SystemExit):b.main(args)
                configure.assert_not_called()
    def test_decoder_keeps_spike_and_gap_flags_and_rejects_wrong_pointer(self):
        ram=bytearray(10000);syms={'dob_real_trace':(0x20000000,84),'dob_real_points':(0x20000060,4),
                                  'mechanical_capture':(0x20000100,4712)}
        ints=[1,2,2000,0,1,1,40000,40060,2000000,2003000,0,100,1,0,0,1,1]
        struct.pack_into('<17I4f',ram,0,*ints,240,240,0,.2)
        struct.pack_into('<I',ram,96,0x20000100)
        struct.pack_into('<II3f2H',ram,256,2000000,2000040,.7,-.77,25,0,1024)
        struct.pack_into('<II3f2H',ram,280,2003000,2003040,.005,.15,25,60,2048+8192+32768)
        h,rows=b.decode_raw(ram,syms)
        self.assertAlmostEqual(rows[0]['id_raw_a'],.7,6)
        self.assertFalse(rows[0]['current_valid']);self.assertEqual(rows[1]['dt_us'],3000)
        self.assertEqual(rows[1]['adc_seq'],40060)
        struct.pack_into('<I',ram,96,0x20000104)
        with self.assertRaises(ValueError):b.decode_raw(ram,syms)
    def test_no_start_no_data_is_not_an_abi_error(self):
        syms={'dob_real_trace':(0x20000000,84),'dob_real_points':(0x20000060,4),
              'mechanical_capture':(0x20000100,4712)}
        header,rows=b.decode_raw(bytes(10000),syms)
        self.assertEqual(rows,[]);self.assertEqual(header['observations'],0)
    def test_irq_inclusive_cost_does_not_replace_original_protection_checks(self):
        row={'terminal_status':{},'raw_capture':{'header':{'max_cycles':8419}}}
        with patch.object(b.normal,'ORIGINAL_EXECUTE'),patch.object(b.normal,'classify',return_value={}):
            b.run_one(row,'test',Path('stage'),b'A')
        self.assertTrue(row['pass_']);self.assertFalse(row['capture_timing']['exclusive_cpu_time_measured'])
        with patch.object(b.normal,'ORIGINAL_EXECUTE'),patch.object(b.normal,'classify',side_effect=RuntimeError('deadline')):
            with self.assertRaisesRegex(RuntimeError,'deadline'):b.run_one({},'test',Path('stage'),b'A')
    def test_contact20_model_check_expects_observe10_not_old20(self):
        with patch.object(b.normal,'configure'),patch.object(b,'image',return_value=b'A'):
            b.configure(b.BASELINE)
            self.assertEqual(b.normal.prior.fb.shadow.MODEL['MIN_W_MRAD_S'],'1047')
    def test_batch_exact_five_then_stop_and_no_retry_on_fault(self):
        stage={'mode':'stage','baseline_restore_receipt':str(b.BASELINE),'dob_feedback_requested':False}
        seen=[]
        def run(row,name,source,data):
            seen.append(source)
            row.update(pass_=True,final_outputs_off=True,final_cpu_halted=True,raw_capture={'quality_pass':True})
        with patch.object(Path,'read_text',return_value=json.dumps(stage)),patch.object(b,'configure',return_value=b'A'),\
             patch.object(b.base.old.prior,'checkpoint'),patch.object(b,'run_one',side_effect=run):
            self.assertEqual(b.main(['--execute-five','stage','--operator-present-five-drive-on-no-alarm-05a']),0)
            self.assertEqual(len(seen),5)
        with patch.object(Path,'read_text',return_value=json.dumps(stage)),patch.object(b,'configure',return_value=b'A'),\
             patch.object(b.base.old.prior,'checkpoint'),patch.object(b,'run_one',side_effect=RuntimeError('protection')) as run:
            self.assertEqual(b.main(['--execute-five','stage','--operator-present-five-drive-on-no-alarm-05a']),1)
            self.assertEqual(run.call_count,1)

if __name__=='__main__':unittest.main()
