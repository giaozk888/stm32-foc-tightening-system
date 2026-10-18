"""Pure offline acceptance-runner checks; no serial/debugger access."""
import struct
import sys
import unittest
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
import cur_confirm_cycles_board_test as board


class CurConfirmBoard(unittest.TestCase):
    def test_pinned_image_and_arm_layout(self):
        self.assertEqual(len(board.image()),227492)
        address,offsets=board.layout()
        self.assertEqual(offsets,board.ARM_LAYOUT)
        self.assertTrue(0x20000000<=address<0x20020000)

    def test_confirmation_decode_is_current_image_schema(self):
        ram=bytearray(0x20000)
        address,offsets=board.layout()
        start=address-0x20000000
        ram[start+offsets[1]]=1
        ram[start+offsets[2]]=1
        ram[start+offsets[3]]=3
        for offset,value in zip(offsets[4:],(10,9,0,4,203)):
            struct.pack_into('<I',ram,start+offset,value)
        decoded=board.decode_confirmation(ram)
        self.assertEqual(tuple(decoded[k] for k in board.STAT_NAMES),(10,9,0,4,203))
        self.assertEqual(decoded['confirm_cycles'],3)
        self.assertTrue(decoded['confirmation_exercised'])
        ram[start+offsets[3]]=5
        with self.assertRaises(ValueError): board.decode_confirmation(ram)
        with self.assertRaises(ValueError): board.decode_confirmation(ram[:-1])

    def test_console_rejects_motion_or_forced_confirmation(self):
        console=object.__new__(board.prior.Console)
        for command in ('START','MOTOR TEST START','FW END','FW CONFIRM','RESET','MOTOR TEST CLEAR'):
            with self.subTest(command=command),self.assertRaises(ValueError): console.query(command)

    def test_full_run_cycle_decode(self):
        ram=bytearray(0x20000)
        address,size=board.ram_symbol('cl_current_cycles')
        self.assertEqual(size,36)
        struct.pack_into('<9I',ram,address-0x20000000,100,7150,100,7150,90,5697,80,4197,0)
        decoded=board.decode_cycles(ram)
        self.assertEqual(decoded['max_cycles'],7150)
        self.assertEqual(decoded['deadline_miss_count'],0)
        self.assertAlmostEqual(decoded['max_us'],42.0588235294)

    def test_new_baseline_must_be_restored_receipt_in_evidence_directory(self):
        with self.assertRaises(ValueError): board.configure(Path('unrelated-receipt.json'))


if __name__=='__main__': unittest.main()
