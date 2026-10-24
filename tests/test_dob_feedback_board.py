import json
from pathlib import Path
import struct
import subprocess
import sys
import unittest
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
import dob_feedback_board as board

class FeedbackBoardTests(unittest.TestCase):
    def test_files_only_hash_and_actual_b1079_default_off(self):
        p=subprocess.run([sys.executable,str(ROOT/'tools/dob_feedback_board.py')],cwd=ROOT,text=True,capture_output=True)
        self.assertEqual(p.returncode,0,p.stdout+p.stderr)
        self.assertIn('no devices',p.stdout)
        r=json.loads(board.ROOT_RESTORE.read_text());self.assertEqual(r['metadata'][5],1079)
        self.assertEqual(r['image_sha256'],board.previous.SHA)
        self.assertFalse(board.FEEDBACK_ON)

    def test_missing_fresh_off_on_never_runs_setup(self):
        for args in (['--prepare-off'],['--execute-once','missing','--feedback-on'],['--restore-b-drive-off','missing']):
            with patch.object(board,'ORIGINAL_SETUP') as setup:
                with self.assertRaises(SystemExit):board.main(args)
                setup.assert_not_called()

    def test_wrong_gain_blocks_before_run_and_on_requires_idle_command(self):
        cfg='1 OK DOBFB ON=0 '+' '.join(k+'='+v for k,v in board.FB_CONFIG.items())
        b=object.__new__(board.FeedbackBoard);b.record={}
        with patch.object(board.shadow.ORIGINAL_BOARD,'command',return_value=cfg.replace('250000','100000')) as send:
            with self.assertRaises(RuntimeError):b.command('MOTOR TEST MECH RUN POS 600')
            self.assertEqual(send.call_count,1)
        with patch.object(board,'FEEDBACK_ON',True),patch.object(board.shadow.ORIGINAL_BOARD,'command',
                side_effect=[cfg,'ERR DOBFB BUSY_OR_OUTPUT_ENABLED']) as send:
            with self.assertRaises(RuntimeError):b.command('MOTOR TEST MECH RUN POS 600')
            self.assertEqual(send.call_args.args[0],'MOTOR TEST MECH DOB FB ON')
        with patch.object(board.shadow.ORIGINAL_BOARD,'command') as send:
            with self.assertRaises(ValueError):b.command('MOTOR TEST MECH RUN NEG 600')
            send.assert_not_called()

    def test_capture_caps_flags_and_modes(self):
        raw=bytearray(80);self.assertEqual(board.decode_feedback(raw)['enabled'],0)
        struct.pack_into('<f',raw,0,.026)
        with self.assertRaises(ValueError):board.decode_feedback(raw)
        struct.pack_into('<f',raw,0,0);struct.pack_into('<I',raw,28,2)
        with self.assertRaises(ValueError):board.decode_feedback(raw)

if __name__=='__main__':unittest.main()
