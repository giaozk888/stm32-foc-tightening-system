import json
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
import dob_pre_lpf_200_board as board

class Board200Tests(unittest.TestCase):
    def test_files_only_new_image_and_actual_v7_b1075_proof(self):
        p=subprocess.run([sys.executable,str(ROOT/'tools/dob_pre_lpf_200_board.py')],
                         cwd=ROOT,text=True,capture_output=True)
        self.assertEqual(p.returncode,0,p.stdout+p.stderr)
        self.assertIn('1 mechanical points; no devices',p.stdout)
        board.image();r=json.loads(board.ROOT_RESTORE.read_text())
        self.assertEqual(r['metadata'][5],1075)
        self.assertTrue(r['pass_'] and r['b_application_not_run'])
        self.assertEqual(r['image_sha256'],board.previous.SHA)

    def test_no_hardware_without_fresh_power_confirmations(self):
        for args in (['--prepare-off'],['--execute-once','missing'],['--restore-b-drive-off','missing']):
            with patch.object(board,'ORIGINAL_SETUP') as setup:
                with self.assertRaises(SystemExit):board.main(args)
                setup.assert_not_called()

    def test_uart_100ma_mismatch_stops_before_motor_command(self):
        cfg='1 OK ADMIT '+' '.join(k+'='+v for k,v in board.CONFIG.items())
        b=object.__new__(board.previous.PreLpfBoard);b.record={}
        with patch.object(board.previous,'CONFIG',board.CONFIG),patch.object(
            board.previous.shadow.DobBoard,'command',return_value=cfg.replace('200000','100000')) as send:
            with self.assertRaises(RuntimeError):b.command('MOTOR TEST MECH RUN POS 600')
            self.assertEqual(send.call_count,1)
            self.assertEqual(send.call_args.args[0],'MOTOR TEST MECH DOB ADMIT CFG')

if __name__=='__main__':unittest.main()
