"""Offline checks for the new pinned, non-actuating board adapter."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
import current_impulse_board_test as board


class BoardAdapterTests(unittest.TestCase):
    def rows(self):
        s = dict(samples='1000', suspect='5', spike='3', transition='1',
            unresolved='1', max_unresolved_run='1', fault='0',
            normal_max_cycles='3400', suspect_max_cycles='500',
            unresolved_max_cycles='600', max_cycles='3500', deadline_miss='0')
        return [dict(s, samples='100'), s]

    def test_exact_image_and_transaction_binding(self):
        data = board.image()
        self.assertEqual(len(data), 225068)
        self.assertEqual(board.tx.image(), data)
        self.assertEqual(board.tx.BASE_META[2:6], (2,0,0,582))
        self.assertEqual(board.prior.SIZE, board.tx.SIZE)
        self.assertEqual(board.tx.mailbox(data)[2:5], (2,2,1))

    def test_new_three_path_statistics(self):
        parsed = board.statistics(['CURRENT VALIDATION '+ ' '.join(
            f'{k}={v}' for k,v in s.items()) for s in self.rows()])
        result = board.validate_statistics(parsed)
        self.assertTrue(result['compute_50us_pass'])
        self.assertEqual(result['observed_normal_max_us'], 20)
        self.assertTrue(result['unresolved_path_observed'])
        self.assertFalse(result['motor_closed_loop_verified'])

    def test_failure_gates(self):
        for key, value in [('fault','1'), ('deadline_miss','1'),
                           ('normal_max_cycles','8500'), ('max_cycles','8500'),
                           ('suspect_max_cycles','8500'),
                           ('unresolved_max_cycles','8500'), ('samples','100')]:
            rows = self.rows()
            rows[-1][key] = value
            with self.subTest(key=key), self.assertRaises(RuntimeError):
                board.validate_statistics(rows)
        rows = self.rows()
        del rows[-1]['suspect_max_cycles']
        with self.assertRaises(RuntimeError):
            board.validate_statistics(rows)

    def test_console_cannot_actuate(self):
        console = object.__new__(board.prior.Console)
        for command in ['START', 'MOTOR TEST START', 'FW CONFIRM', 'RESET',
                        'MOTOR TEST CLEAR', 'ADC RAW START']:
            with self.subTest(command=command), self.assertRaises(ValueError):
                console.query(command)


if __name__ == '__main__':
    unittest.main()
