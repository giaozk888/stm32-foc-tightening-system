import json
from pathlib import Path
import struct
import subprocess
import sys
import unittest
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
import dob_current_admission_board as board


class AdmissionBoardTests(unittest.TestCase):
    def test_files_only_exact_image_and_actual_b1051(self):
        p=subprocess.run([sys.executable,str(ROOT/'tools/dob_current_admission_board.py')],cwd=ROOT,text=True,capture_output=True)
        self.assertEqual(p.returncode,0,p.stdout+p.stderr);self.assertIn('1 mechanical points; no devices',p.stdout)
        board.image();r=json.loads(board.ROOT_RESTORE.read_text())
        self.assertTrue(r['pass_'] and r['b_application_not_run']);self.assertEqual(r['metadata'][5],1051)
        self.assertEqual(r['image_sha256'],board.previous.SHA)

    def test_fresh_off_on_gates_before_setup(self):
        for args in (['--prepare-off'],['--execute-once','missing'],['--restore-b-drive-off','missing']):
            with patch.object(board,'ORIGINAL_SETUP') as setup:
                with self.assertRaises(SystemExit):board.main(args)
                setup.assert_not_called()

    def test_config_unused_trace_before_existing_shadow_readiness_and_single_run(self):
        cfg='1 OK ADMIT '+' '.join(k+'='+v for k,v in board.CONFIG.items())
        initial='2 OK ADMIT V=1 DEC=0 BLOCK=0 WHY=0 N=0 HOLD=0 EXIT=0 FEEDBACK=0'
        trace='3 OK IDTRACE V=2 PRE=32 DENSE=32 TAIL=128 TAIL_US=4000 STATE=0 POST=0 NT=0 RESET=0 FEEDBACK=0'
        def new():b=object.__new__(board.AdmissionBoard);b.record={};return b
        run='MOTOR TEST MECH RUN POS 600'
        with patch.object(board.shadow.DobBoard,'command',side_effect=[cfg,initial,trace,'OK QUEUED']) as send:
            self.assertIn('QUEUED',new().command(run));self.assertEqual(send.call_count,4)
        for bad in ([cfg.replace('RETURN_UA=150000','RETURN_UA=200000')],
                    [cfg,initial.replace('BLOCK=0','BLOCK=1')],
                    [cfg,initial,trace.replace('V=2','V=1')]):
            with patch.object(board.shadow.DobBoard,'command',side_effect=bad) as send:
                with self.assertRaises(RuntimeError):new().command(run)
                self.assertFalse(any(c.args[0]==run for c in send.call_args_list))
        with patch.object(board.shadow.DobBoard,'command') as send:
            with self.assertRaises(ValueError):new().command('MOTOR TEST MECH RUN POS 700')
            send.assert_not_called()

    def test_corrupt_admission_counters_fail_closed(self):
        raw=bytearray(92);struct.pack_into('<I',raw,32,8) # stopped decision
        self.assertFalse(board.decode_admission(raw)['blocked'])
        for offset,val in ((16,2),(28,1),(32,9),(36,0),(52,1),(76,2),(88,5)):
            b=bytearray(raw);struct.pack_into('<I',b,offset,val)
            if offset==36:struct.pack_into('<I',b,40,1) # passed > samples
            with self.assertRaises(ValueError,msg=str(offset)):board.decode_admission(b)

    def test_exact_single_point_stage_metadata(self):
        import tempfile
        valid=dict(speeds_rpm=[600],ka_a_per_rpm_s=board.low.KA,overspeed_trip_rpm=1000,
                   travel_limit_deg=30000,activation=False,motor_commands=0,
                   final_outputs_off=True,final_cpu_halted=True)
        with tempfile.TemporaryDirectory(dir=ROOT/'tmp') as d:
            p=Path(d)/'plan.json';p.write_text(json.dumps(valid))
            with patch.object(board,'ORIGINAL_STAGED',return_value=('source',b'raw')):
                self.assertEqual(board.staged(p,b'image'),('source',b'raw'))
                valid['speeds_rpm']=[600,600];p.write_text(json.dumps(valid))
                with self.assertRaises(ValueError):board.staged(p,b'image')


if __name__=='__main__':unittest.main()
