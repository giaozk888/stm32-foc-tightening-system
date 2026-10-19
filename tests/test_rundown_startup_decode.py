"""Synthetic binary-layout regressions only; no real motor evidence implied."""
from pathlib import Path
import struct
import sys
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
import rundown_startup_decode as decoder


def make_trace():
    data=bytearray(decoder.TRACE_SIZE)
    for index in range(33):
        # Base 3 uint32 + 4 uint16; sixteen floats; delta + dt/seq/count;
        # three pending + three last-written CCR; ten byte flags.
        values=[index*50000,index*1000,100000+index*50000,100,1560,1563,0]
        values += [20,3.662109375,2.77,.35,.02,.10,-.3,.7,0,.2,
                   20,2.5,.25,index*.8,.3,.31]
        values += [-1,1000,index*1000-1 if index else 0,index*1000]
        values += [2000,2100,2200,1999,2099,2199]
        values += [1,1,1,0,0,1,2,3,0,1]
        decoder.FRAME.pack_into(data,index*decoder.FRAME.size,*values)
    struct.pack_into('<4I4B',data,decoder.FRAME.size*33,1000,0,0,32,0,1,0,1)
    return data


class StartupDecodeTests(unittest.TestCase):
    def test_all_link_fields_and_units(self):
        report=decoder.decode(make_trace())
        self.assertEqual(report['total'],32); self.assertTrue(report['terminal_valid'])
        row=report['rows'][1]
        self.assertEqual(row['PWM_pending'],[2000,2100,2200])
        self.assertEqual(row['PWM_applied_preload_readback'],[1999,2099,2199])
        self.assertAlmostEqual(row['Iq_error_A'],.25)
        self.assertAlmostEqual(row['encoder_delta_rpm'],3.662109375)
        self.assertAlmostEqual(row['estimator_delta_rpm_error'],0)
        self.assertEqual(row['rundown_armed'],0)
        self.assertFalse(report['capture_identity_verified'])
        self.assertFalse(report['hardware_access'])

    def test_live_legacy_or_bad_cadence_not_silently_decoded(self):
        data=make_trace()
        for bad in (data[:-1],bytes(2000)):
            with self.assertRaises(ValueError): decoder.decode(bad)
        data[decoder.FRAME.size*33+16]=1
        with self.assertRaisesRegex(ValueError,'frozen'): decoder.decode(data)
        data=make_trace(); struct.pack_into('<I',data,decoder.FRAME.size,1)
        with self.assertRaisesRegex(ValueError,'cadence'): decoder.decode(data)

    def test_matching_size_and_sram_coverage_required_for_elf_extraction(self):
        class Result: stdout='20000020 00001010 b cl_startup\n'
        data=make_trace(); sram=bytes(32)+data
        with patch.object(decoder.subprocess,'run',return_value=Result()):
            self.assertEqual(decoder.extract('x.elf',sram,0x20000000,'nm'),data)
            with self.assertRaisesRegex(ValueError,'cover'): decoder.extract('x.elf',sram[:50],0x20000000,'nm')
        Result.stdout='20000020 000007d0 b cl_startup\n'
        with patch.object(decoder.subprocess,'run',return_value=Result()):
            with self.assertRaisesRegex(ValueError,'schema-2'): decoder.extract('x.elf',sram,0x20000000,'nm')


if __name__=='__main__': unittest.main()
