"""Offline staging contracts; no device access."""
from pathlib import Path
import struct
import sys
import unittest
import zlib
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import feedback_safety_stage as tool

class GuardianStageTests(unittest.TestCase):
    def test_image_exact_and_strictly_hard_off(self):
        self.assertEqual(tool.image_info(tool.image())[0], 'B')

    def test_no_activation_motion_sampling_or_fault_clear(self):
        uart = tool.Console.__new__(tool.Console)
        for cmd in ('FW END', 'FW CONFIRM', 'FW ABORT', 'START', 'CLEAR', 'BOOT B',
                    'BENCH RUN', 'BENCH PROTECTION TEST TIMEOUT', 'ZERO SAMPLE'):
            with self.assertRaises(ValueError): uart.command(cmd)
            with self.assertRaises(ValueError): uart.query(cmd)

    def test_exact_baseline_and_protected_bytes(self):
        a = (ROOT / 'foc2_app_a/build/CurrentObserveOnly20261013/foc2.bin').read_bytes()
        b = (ROOT / 'foc2_app_b/build/SwitchTrendCompare20261013/foc2.bin').read_bytes()
        raw = bytearray(b'\xff'*0x80000)
        raw[0x8000:0x8000+len(a)] = a; raw[0x40000:0x40000+len(b)] = b
        def meta(current=1, pending=0, generation=449):
            payload = struct.pack('<11I', 0x424F4F54,3,current,pending,0,generation,
                                  len(a),zlib.crc32(a),len(b),zlib.crc32(b),0)
            raw[0x7F000:0x7F030] = payload+struct.pack('<I', zlib.crc32(payload))
        meta(); self.assertEqual(tool.baseline(raw)['generation'], 449)
        for kwargs in ({'current':2}, {'pending':2}, {'generation':450}):
            meta(**kwargs)
            with self.assertRaises(RuntimeError): tool.baseline(raw)
        meta(); staged = bytearray(raw); data = tool.image()
        staged[0x40000:0x40000+len(data)] = data
        tool.compare_flash(raw, staged, data, 'B', staged=True)
        for offset in (0,0x8000,0x78000,0x7f800):
            bad = bytearray(staged); bad[offset] ^= 1
            with self.assertRaises(RuntimeError): tool.compare_flash(raw,bad,data,'B',staged=True)

    def test_scope_and_backup_before_stage(self):
        src = Path(tool.__file__).read_text('utf-8')
        self.assertIn('allow_reset=False', src)
        self.assertLess(src.index("before = capture('before')"), src.index('stage(uart,'))
        self.assertIn('before[:0x40000] != after[:0x40000]', src)
        self.assertNotIn("command('FW END'", src)

if __name__ == '__main__': unittest.main()
