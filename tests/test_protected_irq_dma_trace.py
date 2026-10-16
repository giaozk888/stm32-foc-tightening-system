import unittest
from pathlib import Path

import protected_irq_dma_trace_stage as trace


class DmaTraceTests(unittest.TestCase):
    def test_exact_separate_image(self):
        self.assertEqual(len(trace.pinned_image()),206224)
        self.assertNotEqual(trace.SHA,trace.old.SHA)

    def test_baseline_refuses_unrelated_receipt(self):
        with self.assertRaises(RuntimeError):
            trace.verified_baseline(b'',Path('unrelated.json'))

    def test_stage_cannot_activate_or_send_motor_command(self):
        class Port:
            def write(self,_): raise AssertionError('No serial access expected')
        uart=trace.StageConsole(Port())
        with self.assertRaises(ValueError): uart.command('FW END')
        with self.assertRaises(ValueError): uart.query('MOTOR TEST SPEED')
        source=Path(trace.__file__).read_text('utf-8')
        self.assertIn('allow_reset=False',source)
        self.assertIn("board.outputs('A',False)",source)


if __name__=='__main__': unittest.main()
