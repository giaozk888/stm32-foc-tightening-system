import ctypes as C
import json
from pathlib import Path
import struct
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
sys.path.insert(0, str(ROOT / 'tests'))
import prepare_low_recovery as settings
from test_offline_low_recovery import Host
from dob_low_audit_decode import decode_tail, load
from unittest.mock import patch


class AuditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.paths = {}
        for enabled, name in ((False, 'no_audit'), (True, 'with_audit')):
            path = ROOT / 'tmp' / ('low_' + name + '.dll')
            command = [str(settings.GCC), '-std=c11', '-Os', '-Wall', '-Wextra', '-Werror', '-shared',
                       '-include', str(settings.NATIVE / 'host_compat.h'), '-I', str(settings.COMMON),
                       '-I', str(settings.NATIVE), *['-D' + x for x in settings.FLAGS],
                       '-DFOC_DOB_SHORT_LOW_RECOVERY=1', '-DFOC_DOB_TREND_WINDOW75=1',
                       '-DFOC_DOB_TREND_CONTINUOUS=1']
            if enabled:
                command += ['-DFOC_DOB_LOW_AUDIT=1', str(settings.COMMON / 'dob_low_recovery_audit.c')]
            command += [str(ROOT / 'tests/dob_low_audit_host.c'),
                        str(settings.COMMON / 'mechanical_dob_monitor.c'),
                        str(settings.COMMON / 'dob_trend_shadow.c'),
                        str(settings.COMMON / 'dob_trend_continuous.c'), '-lm', '-o', str(path)]
            subprocess.run(command, capture_output=True, text=True, check=True)
            cls.paths[name] = path

    def host(self, name='with_audit'):
        h = Host.__new__(Host)
        h.dll = C.CDLL(str(self.paths[name]))
        h.dll.dob_host_observe.argtypes = [C.POINTER(C.c_double), C.POINTER(C.c_double)]
        h.dll.dob_host_reset.argtypes = [C.POINTER(C.c_double)]
        h.dll.audit_copy.argtypes = [C.c_void_p]
        h.reset()
        return h

    def tail(self, h):
        b = C.create_string_buffer(200)
        h.dll.audit_copy(b)
        return b.raw

    def begin(self, h):
        h.warm()
        for _ in range(4):
            h.step(w=.5)

    def test_first_last_survive_recovery_and_classifier_quality_clear(self):
        h = self.host(); self.begin(h)
        y = h.step(w=.5, id=.7)
        before = decode_tail(self.tail(h))['snapshots']['first']
        self.assertEqual(before['site'], 1)
        self.assertEqual(before['reason'], 2)
        self.assertEqual(before['timestamp_us'], 100000 + h.k * 1000)
        self.assertEqual(before['input_valid'], 1)
        self.assertEqual(before['filter_updated'], 0)
        self.assertAlmostEqual(before['id_a'], .7, places=6)
        self.assertLess(before['abs_id_lpf_a'], .01)
        for _ in range(400): y = h.step()
        self.assertTrue(y[1]); self.assertEqual(y[8], 0)  # Live reason cleared.
        self.assertEqual(decode_tail(self.tail(h))['snapshots']['first'], before)
        saved = self.tail(h)
        self.assertEqual(h.dll.audit_classifier_clear(), 1)
        self.assertEqual(self.tail(h), saved)
        self.begin(h); h.step(w=-.5)
        event = decode_tail(self.tail(h))['snapshots']
        self.assertEqual(event['first'], before)
        self.assertEqual(event['last']['site'], 2)
        self.assertGreater(event['last']['timestamp_us'], before['timestamp_us'])
        self.assertEqual(decode_tail(self.tail(h))['event_count'], 2)

    def test_distinguishes_return_to_low_from_direction_reversal(self):
        h = self.host(); self.begin(h); h.step(); h.step(w=.5)
        event = decode_tail(self.tail(h))['snapshots']['last']
        self.assertEqual(event['site'], 4)
        self.assertEqual(event['mode'], 2)
        self.assertGreater(event['return_elapsed_us'], 0)

    def test_long_low_and_deadline_record_actual_branch(self):
        h = self.host(); self.begin(h)
        for _ in range(110): h.step(w=.5)
        event = decode_tail(self.tail(h))['snapshots']['last']
        self.assertEqual(event['site'], 3)
        self.assertGreater(event['low_elapsed_us'], 100000)
        h.reset(); self.begin(h)
        for _ in range(210): h.step(sat=1)
        event = decode_tail(self.tail(h))['snapshots']['last']
        self.assertEqual(event['site'], 7)
        self.assertGreater(event['return_elapsed_us'], 200000)
        self.assertTrue(event['status'] & 128)

    def test_fault_lifecycle_records_last_actual_epoch(self):
        h = self.host(); self.begin(h); h.step(w=.5, fault=1)
        event = decode_tail(self.tail(h))['snapshots']['last']
        self.assertEqual(event['site'], 8)
        self.assertEqual(event['timestamp_basis'], 'last_actual_sample')
        h.reset()
        self.assertEqual(decode_tail(self.tail(h))['snapshots'], dict(first=None, last=None))

    def test_audit_does_not_change_control_or_estimator_outputs(self):
        a, b = self.host('no_audit'), self.host()
        epochs = ([{}] * 1000 + [dict(w=.5)] * 20 + [dict(w=.5, id=.7)] + [{}] * 500 +
                  [dict(w=.5)] * 150 + [{}] * 400 + [dict(w=.5)] * 10 + [dict(w=-.5)] + [{}] * 400)
        for kwargs in epochs:
            self.assertEqual(a.step(**kwargs), b.step(**kwargs))

    def test_decoder_handles_nonfinite_and_rejects_bad_abi_or_old_elf(self):
        h = self.host(); self.begin(h); h.step(w=float('nan'))
        event = decode_tail(self.tail(h))['snapshots']['last']
        self.assertIsNone(event['omega_rad_s'])
        json.dumps(event, allow_nan=False)
        with self.assertRaises(ValueError): decode_tail(b'')
        raw = bytearray(self.tail(h)); struct.pack_into('<I', raw, 8, 99)
        with self.assertRaises(ValueError): decode_tail(raw)
        with self.assertRaises(ValueError):
            load(ROOT / 'tmp/absent.bin', ROOT / 'foc2_app_a/build/DobShortLowRecoveryCandidate/foc2.elf')

    def test_zero_timestamp_is_not_mistaken_for_empty_record(self):
        raw = bytearray(200)
        struct.pack_into('<18I6f', raw, 0, *([0, 2, 1, 1] + [0] * 14 + [0.] * 6))
        raw[96:192] = raw[:96]
        struct.pack_into('<2I', raw, 192, 0xD10A0001, 1)
        self.assertEqual(decode_tail(raw)['snapshots']['first']['timestamp_us'], 0)

    def test_real_audit_elf_ram_layout_and_physical_entry_gates(self):
        import tempfile
        import dob_low_audit_board as board
        from foc_path_profile_report import symbols
        self.assertEqual(len(board.image()), 229072)
        syms = symbols(board.ELF)
        ram = bytearray(0x20000)
        arena = syms['mechanical_capture'][0]
        ptr = syms['dob_trend_continuous_arena'][0] - 0x20000000
        struct.pack_into('<I', ram, ptr, arena)
        h = self.host(); self.begin(h); h.step(w=.5, id=.7)
        tail = self.tail(h); offset = arena - 0x20000000
        ram[offset+300:offset+400] = tail[:100]
        ram[offset+700:offset+800] = tail[100:]
        with tempfile.TemporaryDirectory(dir=ROOT / 'tmp') as directory:
            path = Path(directory) / 'ram.bin'; path.write_bytes(ram)
            self.assertEqual(load(path, board.ELF), decode_tail(tail))
        with patch.object(board, 'configure') as configure:
            with self.assertRaises(SystemExit): board.main(['--stage-off'])
            configure.assert_not_called()


if __name__ == '__main__':
    unittest.main()
