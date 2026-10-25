import json
import struct
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
import dob_trend_shadow_board as b

class TrendShadowBoardTests(unittest.TestCase):
    def test_pinned_image_and_prior_B_receipt_files_only(self):
        self.assertEqual(len(b.image()),225752)
        r=json.loads(b.ROOT_RESTORE.read_text())
        self.assertTrue(r['b_application_not_run']);self.assertTrue(r['pass_'])

    def test_missing_physical_gates_does_not_configure(self):
        for argv in (['--stage-off'],['--execute-powered','missing'],['--restore-b-drive-off','missing']):
            with patch.object(b,'configure') as configure:
                with self.assertRaises(SystemExit):b.main(argv)
                configure.assert_not_called()

    def test_decode_actual_native_ring_and_missing_data_semantics(self):
        ram=bytearray(0x20000)
        syms={'dob_trend_shadow':(0x20000000,92),'dob_trend_arena':(0x20000060,4),
              'mechanical_capture':(0x20000100,4712)}
        h={key:0 for key in b.HEADER};h.update(abi=1,flags=7,observations=4000,start_us=100000,
            pre_count=32,post_count=112,trigger_head=21,head=133,record_count=460,
            proxy_rise_us=3100000,trend_rise_us=3200000)
        struct.pack_into('<7I2f14I',ram,0,*(h[k] for k in b.HEADER));struct.pack_into('<I',ram,96,0x20000100)
        for k in range(144):
            slot=(21-32+k)%144
            struct.pack_into('<I4fH2B',ram,0x100+b.CLASSIFIER_SIZE+slot*24,
                2844000+k*8000,.002 if k<32 else .037,.1,240,.12,30720+(32768 if k>=32 else 0),4,2)
        decoded,rows=b.decode_capture(ram,syms)
        self.assertEqual(len(rows),144);self.assertEqual(rows[0]['timestamp_us'],2844000)
        self.assertFalse(rows[31]['triggered']);self.assertTrue(rows[32]['triggered'])
        self.assertAlmostEqual(rows[32]['disturbance_a'],.037,places=6)
        self.assertEqual(b.relative_delays(decoded)['rise_relative_delay_ms'],100)
        self.assertIsNone(b.relative_delays(decoded)['fall_relative_delay_ms'])
        decoded['flags']|=32
        self.assertIsNone(b.relative_delays(decoded)['rise_relative_delay_ms'])
        self.assertEqual(b.relative_delays(decoded)['rise_reason'],'trend_already_active_at_proxy')
        decoded['flags']&=~32;decoded['trend_rise_us']=0
        self.assertIsNone(b.relative_delays(decoded)['rise_relative_delay_ms'])
        self.assertIsNone(b.relative_delays(decoded)['absolute_brake_delay_ms'])

    def test_guarded_selection_then_original_bounded_single_start_owner(self):
        class Board:
            def __init__(self):self.commands=[]
            def command(self,cmd):
                self.commands.append(cmd)
                if cmd.endswith('TREND CFG'):d=b.CFG
                elif cmd.endswith('SPEEDS'):d=dict(CONTACT_RPM='20',OBS_MIN_MRPM='10000',FB_MIN_MRPM='20000')
                elif 'FB' in cmd:d=dict(b.normal.FB_CONFIG,ON='0' if cmd.endswith('CFG') else '1')
                else:d={}
                return 'OK '+' '.join(k+'='+v for k,v in d.items())
        row={'postflight':{}};board=Board()
        with patch.object(b.normal,'motion') as motion:b.motion(board,row);motion.assert_called_once()
        self.assertEqual(board.commands[:4],['MOTOR TEST MECH DOB FB CFG','MOTOR TEST MECH DOB FB ON',
            'MOTOR TEST MECH DOB TREND CFG','MOTOR TEST MECH DOB SPEEDS'])
        self.assertNotIn('START',board.commands)

if __name__=='__main__':unittest.main()
