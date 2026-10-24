import copy
import hashlib
import json
from pathlib import Path
import struct
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'tools'))
import mechanical_dob_report as report
from foc_path_profile_report import symbols


def fixture(count=20, timestamp=100000):
    data = bytearray(report.SIZE)
    meta = dict.fromkeys(report.META_KEYS, 0)
    meta.update(version=40, head=count % 16, count=count, observations=count,
                valid_samples=count, positive_n=count, frozen=32,
                positive_sum=.02*count, disturbance_abs_peak=.02,
                last_stored_us=(timestamp+(count-1)*64000) & 0xffffffff)
    for i in range(count):
        end = (timestamp+i*64000) & 0xffffffff
        struct.pack_into('<6I5f', data, 28+(i % 16)*44,
                         end, 20*(i+1), (end-20) & 0xffffffff, end, 0, 1,
                         60, .24, .24, .001, .02)
    struct.pack_into('<6I5f', data, 732, meta['last_stored_us'], 20*count, 0, 0, 32, 0,
                     60, .24, .24, .001, 0)
    struct.pack_into('<12I5f3I', data, 776, *(meta[k] for k in report.META_KEYS))
    return data


class DobReportTests(unittest.TestCase):
    def test_adc_after_encoder_is_legal_same_epoch_not_unsigned_age(self):
        for timestamp in (100000, 0xffffffb0):
            for relative in (-200, -20, 150, 2000):
                data = fixture(count=1, timestamp=timestamp)
                source = (timestamp+relative) & 0xffffffff
                published = (source+(19 if relative < 2000 else 0)) & 0xffffffff
                struct.pack_into('<2I', data, 28+8, source, published)
                row = report.decode_bytes(data)['rows'][0]
                self.assertTrue(row['valid'])
                self.assertEqual(row['adc_relative_to_encoder_us'], relative)
            for relative in (-201, 2001):
                data = fixture(count=1, timestamp=timestamp)
                source = (timestamp+relative) & 0xffffffff
                struct.pack_into('<2I', data, 28+8, source, source)
                with self.assertRaises(ValueError):
                    report.decode_bytes(data)

    def test_ring_wrap_time_wrap_historical_not_live_not_bin_averages(self):
        result = report.decode_bytes(fixture(timestamp=0xffff0000))
        self.assertEqual(len(result['rows']), 16)
        self.assertEqual(result['rows'][0]['adc_seq'], 100)
        self.assertEqual(result['rows'][-1]['adc_seq'], 400)
        self.assertAlmostEqual(result['tail_span_s'], .960)
        self.assertAlmostEqual(result['positive_mean_a'], .02)
        self.assertIsNone(result['negative_mean_a'])
        self.assertFalse(result['feedback_enabled'])
        self.assertFalse(result['live'])
        self.assertEqual(result['current']['reasons'], ['OFF'])
        self.assertIn('instantaneous', result['note'])
        self.assertEqual(report.decode_bytes(bytes(report.SIZE))['rows'], [])

    def test_odd_version_corrupt_metadata_nonfinite_time_quality_and_abi_rejected(self):
        for offset, value in ((776, 41), (780, 16), (784, 21), (792, 21),
                              (816, 7), (844, 0), (28+4*44+20, 2),
                              (28+4*44+16, 1024)):
            data = fixture()
            struct.pack_into('<I', data, offset, value)
            with self.assertRaises(ValueError, msg=str((offset, value))):
                report.decode_bytes(data)
        for offset in (28+4*44+24, 824, 832):
            data = fixture()
            struct.pack_into('<f', data, offset, float('nan'))
            with self.assertRaises(ValueError):
                report.decode_bytes(data)
        data = fixture()
        struct.pack_into('<I', data, 28+5*44, 123)
        with self.assertRaises(ValueError):
            report.decode_bytes(data)
        data = fixture()
        struct.pack_into('<I', data, 28+4*44+8, 0)
        with self.assertRaises(ValueError):
            report.decode_bytes(data)
        with self.assertRaises(ValueError):
            report.decode_bytes(bytes(855))

    def test_exact_new_image_session_provenance_and_frozen_gate(self):
        elf = ROOT/'foc2_app_a/build/MechanicalDobShadowCandidate/foc2.elf'
        sym = symbols(elf)
        monitor_offset = sym['mechanical_dob_monitor'][0]-0x20000000
        image = elf.with_suffix('.bin').read_bytes()
        # Offline fixture only; a previous receipt supplies the shutdown schema,
        # NOT a claim that this new image has run on the board.
        template = json.loads((ROOT/'tmp/mechanical-ident-run-1792713517791586500.json').read_text())
        with tempfile.TemporaryDirectory(dir=ROOT/'tmp') as directory:
            folder = Path(directory)
            ram = bytearray(0x20000)
            ram[monitor_offset:monitor_offset+report.SIZE] = fixture()
            flash = bytearray(512*1024)
            flash[0x8000:0x8000+len(image)] = image
            ram_path, flash_path, receipt = (folder/'ram.bin', folder/'flash.bin', folder/'receipt.json')
            ram_path.write_bytes(ram)
            flash_path.write_bytes(flash)
            row = copy.deepcopy(template)
            row.update(ram_capture=str(ram_path), final_capture=str(flash_path),
                       ram_sha256=hashlib.sha256(ram).hexdigest(),
                       final_sha256=hashlib.sha256(flash).hexdigest(),
                       elf_sha256=hashlib.sha256(elf.read_bytes()).hexdigest(),
                       image_sha256=hashlib.sha256(image).hexdigest())
            receipt.write_text(json.dumps(row))
            decoded = report.decode(receipt, elf)
            self.assertTrue(decoded['board_verified'])
            self.assertAlmostEqual(decoded['model']['coulomb_over_kt'], .1194516824, places=7)
            self.assertFalse(decoded['feedback_enabled'])
            for key in ('ram_sha256', 'final_sha256', 'elf_sha256', 'image_sha256'):
                bad = dict(row, **{key: '0'*64})
                receipt.write_text(json.dumps(bad))
                with self.assertRaises(ValueError, msg=key):
                    report.decode(receipt, elf)
            bad = copy.deepcopy(row)
            bad['final_outputs_off'] = False
            receipt.write_text(json.dumps(bad))
            with self.assertRaises(ValueError):
                report.decode(receipt, elf)
            struct.pack_into('<I', ram, monitor_offset+812, 1)
            struct.pack_into('<I', ram, monitor_offset+816, 0)
            ram_path.write_bytes(ram)
            row['ram_sha256'] = hashlib.sha256(ram).hexdigest()
            receipt.write_text(json.dumps(row))
            with self.assertRaisesRegex(ValueError, 'not stopped/frozen'):
                report.decode(receipt, elf)


if __name__ == '__main__':
    unittest.main()
