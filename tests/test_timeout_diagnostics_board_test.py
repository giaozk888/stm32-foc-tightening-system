"""Offline tests only: pinned image, snapshot layout and non-actuation gates."""
import struct
import sys
import unittest
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
import timeout_diagnostics_board_test as board


class TimeoutBoardTests(unittest.TestCase):
    def test_pinned_compute_image_and_mailbox(self):
        data = board.image()
        self.assertEqual(len(data),227476)
        self.assertEqual(board.tx.image(),data)
        self.assertEqual(board.tx.BASE_META[2:6],(2,0,0,585))
        self.assertEqual(board.tx.mailbox(data)[2:5],(2,2,1))
        self.assertEqual(board.symbols()['foc_fault_snapshot'][1],204)

    def test_snapshot_schema_from_current_elf(self):
        raw = bytearray(0x20000)
        addr = board.symbols()['foc_fault_snapshot'][0]-0x20000000
        values = list(range(51))
        values[8:18] = [n+0.25 for n in range(10)]
        struct.pack_into('<8I10f33I',raw,addr,*values)
        result = board.snapshot(raw)
        self.assertEqual(result['valid'],0)
        self.assertEqual(result['position_deg'],0.25)
        self.assertEqual(result['stall_elapsed_s'],9.25)
        self.assertEqual(result['contact_candidate_ms'],18)
        self.assertEqual(result['protection_flags'],41)
        self.assertEqual(result['timeout_reason'],4)
        self.assertEqual(result['evidence_reason'],42)
        self.assertEqual(result['evidence_misses'],50)
        with self.assertRaises(ValueError):
            board.snapshot(raw[:-1])

    def test_non_actuating_console(self):
        console = object.__new__(board.prior.Console)
        for command in ('START','MOTOR TEST START','FW END','FW CONFIRM',
                        'RESET','MOTOR TEST CLEAR'):
            with self.subTest(command=command),self.assertRaises(ValueError):
                console.query(command)

    def test_other_image_ram_is_never_decoded(self):
        for submitted,vtor in ((False,0x08008000),(True,0x08040000),(True,None)):
            row = dict(activation_submitted=submitted,snapshot_vtor=vtor)
            board.decode_trial_snapshot(row,b'not read')
            self.assertNotIn('fault_snapshot',row)
            self.assertIn('snapshot_not_decoded',row)

    def test_staging_does_not_activate(self):
        commands = board.tx.stage_commands(Path('before.bin'),Path('expected.bin'),
                                            Path('staged.bin'))
        joined = '\n'.join(commands)
        self.assertIn('0x08008000 bin',joined)
        self.assertIn('verify_image',joined)
        self.assertIn('Live Flash changed',joined)
        self.assertNotIn('reset run',joined)
        self.assertNotIn('resume',joined)
        self.assertNotIn('mww 0x2001FFC0',joined)

    def test_prepare_does_not_program_or_activate(self):
        commands = board.prepare_commands(Path('expected.bin'),Path('before.bin'),
                                          Path('after.bin'))
        joined = '\n'.join(commands)
        self.assertIn('Live Flash changed',joined)
        self.assertIn('reset halt',joined)
        self.assertIn('mww 0x2001FFC0 0',joined)
        self.assertLess(joined.index('Live Flash changed'),joined.index('reset halt'))
        for forbidden in ('reset run','resume','flash write','flash erase','program '):
            self.assertNotIn(forbidden,joined)


if __name__ == '__main__':
    unittest.main()
