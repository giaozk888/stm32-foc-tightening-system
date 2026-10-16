"""Updated trial guards; no hardware access."""
from pathlib import Path
import struct
import sys
import unittest
import zlib

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import original_closed_loop_updated_trial as trial


class UpdatedTrialGuards(unittest.TestCase):
    def test_trial_packet_not_forced_confirmation(self):
        words = trial.mailbox(trial.stage.pinned_image())
        self.assertEqual(words[:6], (0x584F424D, 1, 2, 1, 2, 200360))
        self.assertEqual(words[7], zlib.crc32(struct.pack('<7I', *words[:7])))

    def test_historical_or_modified_image_rejected(self):
        bad = bytearray(trial.stage.pinned_image())
        bad[-1] ^= 1
        for data in (bad, bad[:-100]):
            with self.assertRaises(RuntimeError):
                trial.mailbox(data)

    def test_missing_motion_or_cleanup_warning_not_passed(self):
        good = 'IN_MOTION T=0.1s CTRL=20rpm\nPosition change: +1.00 deg\n'
        trial.motion_result_ok(0, good)
        for code, output in ((1, good), (0, ''), (0, 'Position change: +0 deg'),
                             (0, good + 'SAFETY WARNING: stop not verified'),
                             (0, good + 'Restore CONTACT_MS failed: timeout')):
            with self.assertRaises(RuntimeError):
                trial.motion_result_ok(code, output)

    def test_no_flash_writes_or_chip_crc_execution(self):
        source = Path(trial.__file__).read_text('utf-8')
        for forbidden in ('verify_image ', 'flash write_image', 'mass_erase', "'CLEAR'"):
            self.assertNotIn(forbidden, source)
        self.assertIn('error "Staged Flash changed"', source)
        self.assertIn('Runtime 4A/100 profile not observed; no START', source)
        self.assertIn('emergency_off(row, final)', source)


if __name__ == '__main__':
    unittest.main()
