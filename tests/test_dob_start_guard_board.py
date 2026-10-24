import json
from pathlib import Path
import struct
import subprocess
import sys
import unittest
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
import dob_admission_start_guard_board as board


class GuardBoardTests(unittest.TestCase):
    def test_files_only_exact_image_and_actual_b1055(self):
        p=subprocess.run([sys.executable,str(ROOT/'tools/dob_admission_start_guard_board.py')],cwd=ROOT,text=True,capture_output=True)
        self.assertEqual(p.returncode,0,p.stdout+p.stderr);self.assertIn('1 mechanical points; no devices',p.stdout)
        board.image();r=json.loads(board.ROOT_RESTORE.read_text())
        self.assertTrue(r['pass_'] and r['b_application_not_run']);self.assertEqual(r['metadata'][5],1055)
        self.assertEqual(r['image_sha256'],board.previous.SHA)

    def test_fresh_off_on_gates_before_setup(self):
        for args in (['--prepare-off'],['--execute-once','missing'],['--restore-b-drive-off','missing']):
            with patch.object(board,'ORIGINAL_SETUP') as setup:
                with self.assertRaises(SystemExit):board.main(args)
                setup.assert_not_called()

    def test_exact_config_arm_and_unused_v3_before_existing_readiness(self):
        cfg='1 OK ADMIT '+' '.join(k+'='+v for k,v in board.CONFIG.items())
        initial='2 OK ADMIT V=1 DEC=0 BLOCK=0 WHY=0 N=0 HOLD=0 EXIT=0 FEEDBACK=0'
        arm='3 OK ADMIT ARM '+' '.join(k+'='+v for k,v in board.ARM_CONFIG.items())
        trace='4 OK IDTRACE V=3 PRE=16 DENSE=32 TAIL=48 TAIL_US=4000 STATE=0 POST=0 NT=0 RESET=0 FEEDBACK=0'
        def new():b=object.__new__(board.StartGuardBoard);b.record={};return b
        run='MOTOR TEST MECH RUN POS 600'
        with patch.object(board.shadow.DobBoard,'command',side_effect=[cfg,initial,arm,trace,'OK QUEUED']) as send:
            self.assertIn('QUEUED',new().command(run));self.assertEqual(send.call_count,5)
        for bad in ([cfg.replace('RETURN_UA=150000','RETURN_UA=250000')],
                    [cfg,initial,arm.replace('CONFIRM_US=50000','CONFIRM_US=0')],
                    [cfg,initial,arm.replace('ARMED=0','ARMED=1')],
                    [cfg,initial,arm,trace.replace('V=3','V=2')]):
            with patch.object(board.shadow.DobBoard,'command',side_effect=bad) as send:
                with self.assertRaises(RuntimeError):new().command(run)
                self.assertFalse(any(c.args[0]==run for c in send.call_args_list))
        with patch.object(board.shadow.DobBoard,'command') as send:
            with self.assertRaises(ValueError):new().command('MOTOR TEST MECH RUN NEG 600')
            send.assert_not_called()

    def test_guarded_admission_abi_and_corrupt_arming_counters(self):
        raw=bytearray(112);struct.pack_into('<I',raw,32,8)
        self.assertFalse(board.decode_admission(raw)['armed'])
        for offset,value in ((92,2),(96,52001),(108,2),(92,1),(36,1)):
            b=bytearray(raw);struct.pack_into('<I',b,offset,value)
            with self.assertRaises(ValueError,msg=str(offset)):board.decode_admission(b)
        struct.pack_into('<4Ii',raw,92,1,50000,50,51000,-1)
        self.assertEqual(board.decode_admission(raw)['qualify_sign'],-1)


if __name__=='__main__':unittest.main()
