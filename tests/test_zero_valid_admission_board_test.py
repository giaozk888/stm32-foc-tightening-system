"""No devices: pinned image, exact flash scope, UART decoding and safety gates."""
import contextlib
import io
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
import zero_valid_admission_board_test as board


class BoardTests(unittest.TestCase):
    def test_offline_default_cannot_touch_devices(self):
        with patch.object(sys,'argv',['board']),patch.object(board,'debug') as debug,\
                patch.object(board,'open_port') as serial:
            self.assertEqual(board.main(),0)
            debug.assert_not_called(); serial.assert_not_called()

    def test_physical_gate_precedes_device_or_file_access(self):
        for argv in (['--stage-off'],['--trial-powered','x'],
                     ['--stage-off','--drive-12v-off'],['--restore-b-from-trial','x']):
            with patch.object(sys,'argv',['board',*argv]),patch.object(board,'image') as image,\
                    contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit): board.main()
                image.assert_not_called()

    def test_invalid_restore_receipt_prevents_device_access(self):
        with patch.object(Path,'read_text',return_value='{}'),patch.object(board,'debug') as debug:
            with self.assertRaises(ValueError): board.restore({},'unused',Path('unused'),b'')
            debug.assert_not_called()

    def test_changed_image_never_accepted(self):
        with patch.object(Path,'read_bytes',return_value=b'changed'):
            with self.assertRaises(ValueError): board.image()

    def test_scope_and_padding(self):
        data=board.image(); before=board.baseline()
        raw=bytearray(before); end=(0x8000+len(data)+0x7ff)&~0x7ff
        raw[0x8000:end]=data+b'\xff'*(end-0x8000-len(data))
        board.validate_staged(raw,before,data)
        for offset in (0x100,0x40000,0x78000,0x7e800,end-1):
            changed=bytearray(raw); changed[offset]^=1
            with self.assertRaises(ValueError): board.validate_staged(changed,before,data)

    def test_zero_report_bounds_and_physical_tail(self):
        good='OK ZERO CAL valid=4000 reject=55 total=4055 max_consecutive_reject=2 zero_u=1561 zero_v=1560 result=1 STATE=3 REASON=0 FLAGS=0'
        self.assertEqual(board.zero_fields(good)['reject'],55)
        for a,b in [('valid=4000','valid=3999'),('reject=55','reject=81'),
                    ('max_consecutive_reject=2','max_consecutive_reject=3'),
                    ('result=1','result=0'),('FLAGS=0','FLAGS=512'),
                    ('total=4055','total=4101')]:
            with self.assertRaises(ValueError): board.zero_fields(good.replace(a,b))
        self.assertEqual(board.zero_fields(good.replace('total=4055','total=4059'))['total'],4059)
        with self.assertRaises(ValueError): board.zero_fields('OK ZERO CAL STATE=3')


if __name__=='__main__': unittest.main()
