"""Offline voltage batch command identity, raw ABI and no old-current command."""
import copy
from pathlib import Path
import struct
import subprocess
import sys
import unittest
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
import motor_ident_voltage_batch as b
import test_motor_identification_board as transport


class VoltageBatchTests(unittest.TestCase):
    def test_default_pins_no_device_and_policy_strict(self):
        self.assertEqual(len(b.image()),214716)
        p=subprocess.run([sys.executable,str(ROOT/'tools/motor_ident_voltage_batch.py')],
            capture_output=True,text=True,timeout=15)
        self.assertEqual(p.returncode,0,p.stdout+p.stderr);self.assertIn('no devices',p.stdout)
        self.assertEqual(b.policy('OK MID VOLTAGE_STEP=1 PI_BYPASS=1 STEP_MV=50 STEP_US=100000 END_US=104000 RAW_FRAME_ABI=1')['PI_BYPASS'],'1')
        with self.assertRaises(ValueError):b.policy('OK MID VOLTAGE_STEP=1 PI_BYPASS=0')

    def test_raw_frame_not_old_float_reference_abi(self):
        raw=struct.pack('<3I4H6f4B',99800,2000,1999,1530,1540,3000,1,.01,.02,.05,0.,1.2,0.,2,2,0,0)
        self.assertEqual(len(raw),48)
        wire='1 OK MID K=0 US=99800 SEQ=2000 PSEQ=1999 M=2 S=2 F=0 RU=1530 RV=1540 TCNT=3000 TDIR=1 D=10000 Q=20000 VD=50000 VQ=0 A=1200000 RPM=0'
        out=b.decode_wire(wire)
        self.assertEqual(out[0]['RU'],1530)
        with self.assertRaises(ValueError):b.decode_wire(wire.replace(' RU=1530',''))
        with self.assertRaises(ValueError):b.decode_wire(wire+'\n'+wire.replace('RV=1540','RV=1541'))

    def test_single_voltage_command_closes_and_unknown_ack_not_retried(self):
        helper=transport.IdentBoardTests()
        for axis in ('LD','LQ'):
            cmd='MOTOR TEST IDENT %sV 50MV LOCKED CONFIRM'%axis
            for refuse in (False,True):
                board=transport.FakeBoard(refuse);row={'postflight':{}}
                with patch.object(b.run,'COMMAND',cmd),patch.object(b.run,'EXTRA_READOUT',None),helper.motion_patches():
                    if refuse:
                        with self.assertRaises(TimeoutError):b.axis.ORIGINAL_MOTION(board,row,ident_mode=axis,voltage_step=True)
                    else:b.axis.ORIGINAL_MOTION(board,row,ident_mode=axis,voltage_step=True)
                self.assertEqual(board.calls.count(cmd),1)
                self.assertIn('ANALOG SAFE',board.calls)
                self.assertFalse(any('RS_VALIDATED' in x or 'START'==x for x in board.calls))

    def test_six_point_wrapper_cannot_send_historical_current_command(self):
        seen=[]
        def point(row,name,source,before,data,first):
            seen.append((row['axis'],b.run.COMMAND,row['test']))
        with patch.object(b.previous.shared,'run_point',side_effect=point),patch.dict(b.run.__dict__,{}):
            for mode in ('LD','LQ'):
                row={'axis':mode};b.point(row,'offline',Path('unused'),b'',b'',False)
                self.assertTrue(row['voltage_step']);self.assertTrue(row['pi_bypassed'])
        self.assertEqual([s[1] for s in seen],['MOTOR TEST IDENT LDV 50MV LOCKED CONFIRM','MOTOR TEST IDENT LQV 50MV LOCKED CONFIRM'])
        self.assertTrue(all(s[2]['nonzero_max_us']==4000 for s in seen))


if __name__=='__main__':unittest.main()
