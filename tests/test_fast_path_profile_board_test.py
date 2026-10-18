"""Offline-only runner checks: no debugger/serial access."""
import json
import struct
import subprocess
import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
import fast_path_profile_board_test as board


class BoardProfileTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): board.configure()

    def test_image_and_elf_layout(self):
        self.assertEqual(len(board.image()),229220)
        board.verify_symbols()
        self.assertEqual(board.tx.image(),board.image())
        self.assertEqual(board.confirm.ELF,board.ELF)

    def test_fallback_receipt_and_mailbox(self):
        row=json.loads(board.BASE_RECEIPT.read_text('utf-8'))
        self.assertEqual(row['final_sha256'],board.BASE_SHA)
        self.assertEqual(tuple(row['final_metadata']),board.BASE_META)
        self.assertEqual(board.tx.mailbox(board.image())[2:5],(2,2,1))

    def test_commands_are_stage_only(self):
        commands=board.tx.stage_commands(Path('live.bin'),Path('expected.bin'),Path('stage.bin'))
        text='\n'.join(commands)
        self.assertIn('0x08008000 bin',text)
        self.assertIn('verify_image',text)
        for forbidden in ('reset run','resume','mww 0x2001FFC0'):
            self.assertNotIn(forbidden,text)

    def test_console_cannot_start_or_force_confirm(self):
        console=object.__new__(board.prior.Console)
        for text in ('START','MOTOR TEST START','FW END','FW CONFIRM','RESET','MOTOR TEST CLEAR'):
            with self.assertRaises(ValueError): console.query(text)

    def test_cross_image_ram_is_not_decoded(self):
        for vtor in (None,0x08040000):
            row=dict(activation_submitted=True,snapshot_vtor=vtor,ram_backup='not read')
            board.decode(row,board.image())
            self.assertIn('snapshot_not_decoded',row)
            self.assertNotIn('fast_path_profile',row)

    def test_confirmation_unchanged_in_new_elf(self):
        raw=bytearray(0x20000)
        address,offsets=board.confirm.layout()
        for offset,value in zip(offsets[4:],(244,244,0,2,115)):
            struct.pack_into('<I',raw,address-0x20000000+offset,value)
        stats=board.confirm.decode_confirmation(raw)
        self.assertEqual(stats['clear_good_samples'],2)
        self.assertEqual(stats['max_cycles_limit'],4)
        self.assertEqual(stats['cur_confirm_fault_count'],0)

    def test_power_phase_required_before_hardware(self):
        p=subprocess.run([sys.executable,str(board.ROOT/'tools/fast_path_profile_board_test.py'),
            '--stage-inactive-a'],capture_output=True,text=True)
        self.assertNotEqual(p.returncode,0)
        self.assertIn('Drive 12 V off',p.stderr)


if __name__=='__main__': unittest.main()
