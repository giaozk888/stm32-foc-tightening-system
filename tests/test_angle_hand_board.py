"""Files/mocks only: never opens a UART or debugger."""
import importlib.util
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
import angle_hand_board as board


class HandBoardTests(unittest.TestCase):
    def test_pinned_hand_image_and_preserved_baseline(self):
        self.assertEqual(len(board.image()),223380)
        self.assertEqual(board.old.zero.latest_meta(board.baseline())[2:6],(2,0,0,709))

    def test_default_has_no_hardware_access(self):
        result=subprocess.run([sys.executable,str(ROOT/'tools/angle_hand_board.py')],
            capture_output=True,text=True,cwd=ROOT)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertIn('no devices or motor commands',result.stdout)

    def test_stage_refuses_without_off_before_debug(self):
        with patch.object(board.hw,'debug') as debug:
            with self.assertRaises(ValueError): board.stage({'physical_power_off':False},'mock',board.image())
            debug.assert_not_called()

    def test_stage_writes_only_inactive_a_and_never_resumes(self):
        before=board.baseline(); data=board.image()
        end=(0x8000+len(data)+0x7ff)&~0x7ff
        raw=before[:0x8000]+data+b'\xff'*(end-0x8000-len(data))+before[end:]
        calls=[]
        with tempfile.TemporaryDirectory(dir=ROOT/'tmp') as directory:
            root=Path(directory)
            def debug(row,commands):
                calls.append(commands)
                (root/'mock-staged.bin').write_bytes(raw)
                return 'mock-off-proof'
            with patch.object(board,'TMP',root),patch.object(board.hw,'debug',side_effect=debug),\
                 patch.object(board.hw,'check_off',return_value={}),\
                 patch.object(board.old.prior,'checkpoint'):
                row={'physical_power_off':True}
                board.stage(row,'mock',data)
            self.assertTrue(row['pass_']); self.assertFalse(row['activation'])
            commands='\n'.join(c for call in calls for c in call)
            self.assertIn('0x08008000 bin',commands)
            self.assertNotIn('reset run',commands)
            self.assertNotIn('resume',commands)
            self.assertNotIn('0x08040000 bin',commands)
            self.assertEqual(commands.count('flash write_image erase'),1)

    def test_board_script_no_motion_or_offset_commands(self):
        source=(ROOT/'tools/angle_hand_board.py').read_text('utf-8')
        self.assertNotIn("query('START",source)
        self.assertNotIn("query('MOTOR TEST TORQUE",source)
        self.assertNotIn('OFFSET +',source)
        self.assertIn("hw.write_mailbox(previous.previous.mailbox(2,2,1",source)
        self.assertIn("GEN=row['health_wait']['confirmed_generation']",source)


if __name__=='__main__': unittest.main()
