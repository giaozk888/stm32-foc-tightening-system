import json
from pathlib import Path
import struct
import sys
import unittest
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
import dob_trend_continuous_board as b

class ContinuousBoardTests(unittest.TestCase):
    def test_native_memory_roundtrip_full_span_mean_quantization_and_late_events(self):
        native=(ROOT/'tmp/dob-trend-continuous-Os.bin').read_bytes()
        self.assertEqual(len(native),4708)
        ram=bytearray(0x20000);ram[:100]=native[:100];struct.pack_into('<I',ram,100,0x20000100)
        ram[0x100:0x100+4608]=native[100:]
        syms=dict(dob_trend_continuous=(0x20000000,100),dob_trend_continuous_arena=(0x20000064,4),mechanical_capture=(0x20000100,4712))
        h,rows,events,coverage=b.decode_capture(ram,syms)
        self.assertEqual(h['observations'],8000);self.assertEqual(len(rows),134)
        self.assertAlmostEqual(rows[0]['time_from_run_start_s'],0)
        self.assertAlmostEqual(rows[-1]['time_from_run_start_s'],7.98)
        self.assertAlmostEqual(coverage['classifier_span_s'],7.999)
        self.assertTrue(coverage['full_observed_run']);self.assertTrue(coverage['event_timeline_complete'])
        self.assertTrue(any(x['time_from_run_start_s']>6 and x['event']=='trend_changed' for x in events))
        self.assertEqual(rows[100]['iq_a'],.123);self.assertEqual(rows[100]['speed_meas_rpm'],240)
        self.assertGreater(rows[100]['directional_mean_a'],.1)
        # Last accepted source timestamp is NOT the classifier's last call.
        struct.pack_into('<I',ram,0x100+964,7000000)
        _,_,_,coverage=b.decode_capture(ram,syms)
        self.assertAlmostEqual(coverage['classifier_span_s'],7.999)
        # Impossible count/head closure cannot be reported as a valid trace.
        struct.pack_into('<I',ram,52,1)
        with self.assertRaises(ValueError):b.decode_capture(ram,syms)

    def test_exact_image_has_only_one_recorder_allocation(self):
        self.assertEqual(len(b.image()),226332)

    def test_quality_reset_cannot_be_reported_as_measured_unload_delay(self):
        h={k:0 for k in b.HEADER};h.update(flags=3,proxy_rise_us=1000000,trend_rise_us=1030000,
            proxy_fall_us=2000000,trend_fall_us=2100000)
        result=b.qualify_relative_delays(h,[dict(event='quality_reset',timestamp_us=1500000)])
        self.assertEqual(result['rise_relative_delay_ms'],30)
        self.assertIsNone(result['fall_relative_delay_ms'])
        self.assertEqual(result['fall_unqualified_proxy_difference_ms'],100)
        self.assertEqual(result['fall_reason'],'quality_reset_interrupts_episode')
        h['event_dropped']=1
        self.assertIsNone(b.qualify_relative_delays(h,[])['rise_relative_delay_ms'])

    def test_missing_power_confirmation_never_configures(self):
        for args in (['--stage-off'],['--execute-powered','missing'],['--restore-b-drive-off','missing']):
            with patch.object(b,'configure') as configure:
                with self.assertRaises(SystemExit):b.main(args)
                configure.assert_not_called()

    def test_new_abi_and_actual500_limits_mandatory_before_original_single_start(self):
        class Board:
            def __init__(self,abi):self.abi=abi;self.commands=[]
            def command(self,c):
                self.commands.append(c)
                if c.endswith('LIMITS'):d=b.prior.LIMITS
                elif c.endswith('TREND CFG'):d=dict(b.CFG,ABI=self.abi)
                elif c.endswith('SPEEDS'):d=dict(CONTACT_RPM='20',OBS_MIN_MRPM='10000',FB_MIN_MRPM='20000')
                elif 'FB' in c:d=dict(b.normal.FB_CONFIG,ON='0' if c.endswith('CFG') else '1')
                else:d={}
                return 'OK '+' '.join(k+'='+v for k,v in d.items())
        with patch.object(b.normal,'motion') as motion:
            with self.assertRaises(RuntimeError):b.motion(Board('1'),{'postflight':{}})
            motion.assert_not_called()
            good=Board('2');b.motion(good,{'postflight':{}});motion.assert_called_once()
            self.assertEqual(good.commands[0],'MOTOR TEST MECH DOB LIMITS')

if __name__=='__main__':unittest.main()
