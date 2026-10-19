"""Fixed +/-100mA preparation, sampled travel/oscillation statistics; no hardware."""
import json
import contextlib
import io
from pathlib import Path
import struct
import subprocess
import sys
import unittest
from unittest.mock import patch
from test_rundown_startup_decode import make_trace
from test_torque_chain import GCC

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
import torque_chain_decode as decoder
import rundown_startup_decode as startup


def capture(angles,sign):
    data=make_trace()
    for i in range(33):
        values=list(startup.FRAME.unpack_from(data,i*startup.FRAME.size))
        values[0]=i*8000
        values[10]=sign*.1; values[11]=-.02; values[12]=sign*.1
        values[20]=angles[i] if i<len(angles) else 999.0 # terminal must be excluded
        startup.FRAME.pack_into(data,i*startup.FRAME.size,*values)
    struct.pack_into('<4I4B',data,startup.FRAME.size*33,1000,0,0,len(angles),0,1,0,1)
    return data


class Torque100Tests(unittest.TestCase):
    def test_forward_monotonic_chain_and_mean_fields(self):
        report=decoder.analyze(capture([0,.25,.5,1],1),1,0,100)
        s=report['statistics']
        self.assertEqual(report['Iq_command_A'],.1)
        self.assertEqual(report['IdRef_A'],0)
        self.assertAlmostEqual(s['mean_Iq_A'],.1,places=6)
        self.assertAlmostEqual(s['mean_Id_A'],-.02,places=6)
        self.assertAlmostEqual(s['mean_abs_Iq_A'],.1,places=6)
        self.assertAlmostEqual(s['mean_abs_Id_A'],.02,places=6)
        self.assertEqual(s['net_mechanical_travel_deg'],1)
        self.assertEqual(s['total_absolute_travel_deg'],1)
        self.assertEqual(s['max_positive_excursion_deg'],1)
        self.assertEqual(s['max_negative_excursion_deg'],0)
        self.assertEqual(s['directionality_ratio'],1)

    def test_reverse_monotonic_and_signed_excursion(self):
        report=decoder.analyze(capture([2,1.5,1,0],-1),-1,0,100)
        s=report['statistics']
        self.assertEqual(report['Iq_command_A'],-.1)
        self.assertEqual(s['net_mechanical_travel_deg'],-2)
        self.assertEqual(s['total_absolute_travel_deg'],2)
        self.assertEqual(s['max_negative_excursion_deg'],-2)
        self.assertEqual(s['max_negative_excursion_abs_deg'],2)
        self.assertEqual(s['max_positive_excursion_deg'],0)
        self.assertEqual(s['directionality_ratio'],1)
        self.assertEqual(s['opposite_direction_intervals'],0)

    def test_oscillation_not_hidden_by_small_net_travel(self):
        for sign in (-1,1):
            s=decoder.analyze(capture([0,sign*.5,-sign*.25,sign*.75],sign),sign,0,100)['statistics']
            self.assertEqual(s['net_mechanical_travel_deg'],sign*.75)
            self.assertEqual(s['total_absolute_travel_deg'],2.25)
            self.assertAlmostEqual(s['directionality_ratio'],1/3)
            self.assertGreater(s['opposite_direction_intervals'],0)
            self.assertEqual(s['max_positive_excursion_deg'],.75 if sign>0 else .25)
            self.assertEqual(s['max_negative_excursion_deg'],-.25 if sign>0 else -.75)

    def test_zero_and_sub_lsb_travel_still_counted_without_terminal(self):
        zero=decoder.analyze(capture([3,3,3],1),1,0,100)['statistics']
        self.assertEqual(zero['total_absolute_travel_deg'],0)
        self.assertIsNone(zero['directionality_ratio'])
        s=decoder.analyze(capture([0,.005,-.005],1),1,0,100)['statistics']
        self.assertAlmostEqual(s['total_absolute_travel_deg'],.015,places=6)
        self.assertAlmostEqual(s['net_mechanical_travel_deg'],-.005,places=6)
        self.assertEqual(s['stationary_intervals'],2)
        self.assertLess(s['max_positive_excursion_deg'],1) # terminal 999 is not a drive frame

    def test_no_150ma_no_sweep_and_presets_default_off(self):
        with self.assertRaises(ValueError): decoder.analyze(capture([0,1],1),1,0,150)
        with self.assertRaises(ValueError): decoder.analyze(capture([0,1],1),1,5,100)
        for slot in 'ab':
            presets=json.loads((ROOT/f'foc2_app_{slot}/CMakePresets.json').read_text())
            p=next(x for x in presets['configurePresets'] if x['name']=='TorqueChain100mADiagnostic')
            self.assertEqual(p['cacheVariables']['FOC_TORQUE_CHAIN_IQ_MA'],'100')
            p=next(x for x in presets['configurePresets'] if x['name']=='TorqueChainDiagnostic')
            self.assertEqual(p['cacheVariables']['FOC_TORQUE_CHAIN_IQ_MA'],'50')
        result=subprocess.run([GCC,'-x','c','-fsyntax-only','-DFOC_TORQUE_CHAIN_IQ_MA=150',
            '-I',str(ROOT/'firmware_common'),'-include','foc_torque_chain_diag.h','-'],
            input='int main(void){return 0;}',capture_output=True,text=True)
        self.assertNotEqual(result.returncode,0)
        self.assertIn('supports only',result.stderr)

    def test_metadata_uses_old_padding_without_buffer_growth(self):
        self.assertEqual(decoder.META.size,20)
        packed=decoder.META.pack(100,-1,0,1,0,1,0,0,0,100)
        self.assertEqual(struct.unpack_from('<H',packed,18)[0],100)
        # Historical zero padding remains distinguishable; never label old 50mA as100mA.
        old=decoder.META.pack(100,1,0,1,0,1,0,0,0,0)
        self.assertEqual(struct.unpack_from('<H',old,18)[0],0)
        self.assertEqual(decoder.analyze(capture([0,1],1),1,0)['Iq_command_A'],.05)

    def test_cli_uses_recorded_100ma_not_legacy_default(self):
        meta=dict(used=1,queued=0,admitting=0,active=0,sign=-1,
                  offset_electrical_deg=0,iq_mA=100)
        output=io.StringIO()
        with patch.object(sys,'argv',['decode','--elf','offline.elf','--sram','offline.bin']), \
             patch.object(Path,'read_bytes',return_value=b''), \
             patch.object(decoder,'metadata',return_value=meta), \
             patch.object(startup,'extract',return_value=capture([0,-1,-2],-1)), \
             contextlib.redirect_stdout(output):
            decoder.main()
        report=json.loads(output.getvalue())
        self.assertEqual(report['Iq_command_A'],-.1)
        self.assertEqual(report['metadata']['iq_mA'],100)
        self.assertFalse(report['hardware_access'])
        self.assertFalse(report['automatic_zero_selection'])


if __name__=='__main__': unittest.main()
