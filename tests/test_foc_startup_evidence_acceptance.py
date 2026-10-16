"""Offline-only pinned A trial gates; no physical device connections."""
import struct
import unittest
from unittest.mock import patch
from pathlib import Path
import zlib

import foc_startup_evidence_acceptance as acceptance


class StartupAcceptanceTests(unittest.TestCase):
    def test_trial_is_exact_b_to_a(self):
        words = acceptance.trial_words()
        self.assertEqual(words[:5], (0x584F424D, 1, 2, 2, 1))
        self.assertEqual(words[5:7], (211004, zlib.crc32(acceptance.stage.pinned_image())))
        self.assertEqual(words[7], zlib.crc32(struct.pack('<7I', *words[:7])))

    def test_no_programming_and_single_activation(self):
        commands = acceptance.activation_commands(Path('live.bin'), Path('prior.bin'))
        self.assertEqual(commands.count('reset run'), 1)
        self.assertEqual(commands.count('reset halt'), 1)
        self.assertFalse(any(c.startswith('flash ') for c in commands))
        self.assertTrue(any('Live Flash changed' in c for c in commands))
        self.assertFalse(any('0x08008000 bin' in c for c in commands))

    def test_default_never_loads_private_or_hardware(self):
        with patch('sys.argv', ['acceptance']), patch.object(acceptance, 'load_stage') as private:
            with patch.object(acceptance, 'open_port') as port:
                acceptance.main()
                private.assert_not_called()
                port.assert_not_called()

    def test_readiness_requires_a_and_off(self):
        fw = 'OK CURRENT=A CONFIRMED=A PENDING=- ATTEMPTS=0 ACTIVE=0'
        health = 'OK READY=1 MASK=0x000'
        status = 'OK MODE=IDLE BUSY=0 FLT=0'
        safe = 'OK LATCHED=0 SD=0 MOE=0'
        acceptance.require_ready(fw, health, status, safe)
        for rows in ((fw.replace('CONFIRMED=A', 'CONFIRMED=B'), health, status, safe),
                     (fw, health, status, safe.replace('SD=0', 'SD=1')),
                     (fw, health, status.replace('FLT=0', 'FLT=1'), safe)):
            with self.assertRaises(RuntimeError):
                acceptance.require_ready(*rows)

    def test_trace_config_and_motion_rejection(self):
        line = 'OK STARTUP CONFIG ENABLED=1 ROWS=32 FIRST_CAUSE=1 BYTES=2000'
        acceptance.trace_config(line)
        for bad in (line.replace('32', '31'), line.replace('FIRST_CAUSE=1', 'FIRST_CAUSE=0')):
            with self.assertRaises(RuntimeError):
                acceptance.trace_config(bad)
        # Rejection occurs before any port access.
        uart = acceptance.Console.__new__(acceptance.Console)
        for text in ('START', 'MOTOR TEST SPEED', 'FW END', 'RESET', 'FAULT CLEAR'):
            with self.assertRaises(ValueError):
                uart.query(text)


if __name__ == '__main__':
    unittest.main()
