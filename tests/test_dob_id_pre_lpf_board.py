import json
from pathlib import Path
import struct
import subprocess
import sys
import unittest
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
import dob_id_pre_lpf_board as board

class PreLpfBoardTests(unittest.TestCase):
    def test_files_only_exact_image_and_actual_b1071(self):
        p=subprocess.run([sys.executable,str(ROOT/'tools/dob_id_pre_lpf_board.py')],cwd=ROOT,text=True,capture_output=True)
        self.assertEqual(p.returncode,0,p.stdout+p.stderr)
        self.assertIn('1 mechanical points; no devices',p.stdout)
        board.image();r=json.loads(board.ROOT_RESTORE.read_text())
        self.assertTrue(r['pass_'] and r['b_application_not_run']);self.assertEqual(r['metadata'][5],1071)
        self.assertEqual(r['image_sha256'],board.previous.SHA)

    def test_fresh_off_on_required_before_setup(self):
        for args in (['--prepare-off'],['--execute-once','missing'],['--restore-b-drive-off','missing']):
            with patch.object(board,'ORIGINAL_SETUP') as setup:
                with self.assertRaises(SystemExit):board.main(args)
                setup.assert_not_called()

    def test_exact_prefilter_trusted_identity_and_unused_state_before_motion(self):
        cfg='1 OK ADMIT '+' '.join(k+'='+v for k,v in board.CONFIG.items())
        initial='2 OK ADMIT V=1 DEC=0 BLOCK=0 WHY=0 N=0 HOLD=0 EXIT=0 FEEDBACK=0'
        arm='3 OK ADMIT ARM '+' '.join(k+'='+v for k,v in board.ARM_CONFIG.items())
        trace='4 OK IDTRACE V=7 PRE=16 DENSE=24 TAIL=32 TAIL_US=16000 STATE=0 POST=0 NT=0 RESET=0 FEEDBACK=0'
        gap='5 OK ADMIT GAPS V=1 STALE=0 RESET=0 RECOVER=0 GAP_US=0 FEEDBACK=0'
        persist='6 OK PERSIST '+' '.join(k+'='+v for k,v in board.PERSIST_CONFIG.items())
        quality='7 OK QUALITY '+' '.join(k+'='+v for k,v in board.QUALITY_CONFIG.items())
        def new():b=object.__new__(board.PreLpfBoard);b.record={};return b
        run='MOTOR TEST MECH RUN POS 600'
        with patch.object(board.shadow.DobBoard,'command',side_effect=[cfg,initial,arm,trace,gap,persist,quality,'OK QUEUED']) as send:
            self.assertIn('QUEUED',new().command(run));self.assertEqual(send.call_count,8)
        for bad in ([cfg.replace('MODE=PREFILTER','MODE=PERSIST')],[cfg.replace('REF=TRUSTED','REF=RAW')],
                    [cfg.replace('FEEDBACK=0','FEEDBACK=1')],
                    [cfg,initial,arm,trace.replace('V=7','V=6')],
                    [cfg,initial,arm,trace,gap,persist,quality.replace('PENDING=0','PENDING=1')]):
            with patch.object(board.shadow.DobBoard,'command',side_effect=bad) as send:
                with self.assertRaises(RuntimeError):new().command(run)
                self.assertFalse(any(c.args[0]==run for c in send.call_args_list))
        with patch.object(board.shadow.DobBoard,'command') as send:
            with self.assertRaises(ValueError):new().command('MOTOR TEST MECH RUN POS 700')
            send.assert_not_called()

    def test_204byte_state_accepts_quarantine_but_rejects_latch_legacy_corruption(self):
        raw=bytearray(204);struct.pack_into('<I',raw,32,8)
        self.assertFalse(board.decode_admission(raw)['armed'])
        for off,value in ((20,2),(28,1),(32,6),(32,14),(32,15),(48,1),(52,1),(56,1),
                          (112,2),(124,1),(136,1),(144,2),(152,1),(180,2),(184,512),(200,2)):
            b=bytearray(raw);struct.pack_into('<I',b,off,value)
            with self.assertRaises(ValueError,msg=str((off,value))):board.decode_admission(b)
        struct.pack_into('<4Ii',raw,92,1,50000,50,51000,1)
        struct.pack_into('<I',raw,20,1);struct.pack_into('<I',raw,32,16)
        struct.pack_into('<2I',raw,124,1,1)
        self.assertEqual(board.decode_admission(raw)['decision'],16)

if __name__=='__main__':unittest.main()
