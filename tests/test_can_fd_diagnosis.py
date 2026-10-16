import importlib.util
from pathlib import Path
import sys
import struct
import unittest
import zlib
from unittest.mock import patch

TOOLS = Path(__file__).resolve().parents[1] / 'tools'
sys.path.insert(0, str(TOOLS))
spec = importlib.util.spec_from_file_location('can_fd_diagnosis', TOOLS / 'can_fd_diagnosis.py')
diag = importlib.util.module_from_spec(spec)
spec.loader.exec_module(diag)
trial_spec = importlib.util.spec_from_file_location('can_fd_trial_existing', TOOLS / 'can_fd_trial_existing.py')
trial = importlib.util.module_from_spec(trial_spec)
trial_spec.loader.exec_module(trial)


class DiagnosisTests(unittest.TestCase):
    def registers(self, **kwargs):
        values = {'state': 0, 'interrupt': 0, 'rx_errors': 0, 'tx_errors': 0}
        values.update(kwargs)
        return values

    def test_warning_cannot_be_cancelled_by_zero_counters(self):
        self.assertIn('hardware_warning', diag.fault_reasons(self.registers(state=16)))

    def test_software_warning_rejects_healthy_hardware_snapshot(self):
        interface = {'linkinfo': {'info_data': {'state': 'ERROR-WARNING',
                    'berr_counter': {'tx': 0, 'rx': 0}}, 'info_xstats': {}}}
        self.assertIn('software_state', diag.fault_reasons(self.registers(), interface))

    def test_bare_vendor_error_frame_is_still_a_fault(self):
        self.assertIn('socketcan_error_frame', diag.fault_reasons(self.registers(), error_frame=True))

    def test_one_shot_clear_on_read_register(self):
        reader = diag.CanRegisters.__new__(diag.CanRegisters)
        reader.memory = bytes(4096)
        reader.error_read = False
        self.assertEqual(reader.first_error_code()['raw'], 0)
        with self.assertRaises(RuntimeError): reader.first_error_code()

    def test_captured_crc_error_decoding(self):
        reader = diag.CanRegisters.__new__(diag.CanRegisters)
        reader.memory = bytearray(4096)
        struct.pack_into('<I', reader.memory, diag.ERROR_CODE, 0x12010200)
        reader.error_read = False
        result = reader.first_error_code()
        self.assertEqual(result['type_field'], 'crc')
        self.assertTrue(result['direction_rx'])
        self.assertTrue(result['receive_crc_segment'])
        self.assertTrue(result['transmit_idle'])
        self.assertFalse(result['data_phase'])

    def test_periodic_whitelist_excludes_error_and_fifo(self):
        self.assertNotIn(diag.ERROR_CODE, diag.REGISTERS.values())
        self.assertTrue(all(offset < 0x200 for offset in diag.REGISTERS.values()))
        self.assertNotIn(4, diag.REGISTERS.values())  # No command register.

    def test_no_permission_does_not_touch_hardware(self):
        with patch.object(diag, 'guarded_boot') as guard:
            with self.assertRaises(RuntimeError): diag.monitor(180, False)
            guard.assert_not_called()

    def test_limit_rejected_before_hardware(self):
        with patch.object(diag, 'guarded_boot') as guard:
            with self.assertRaises(RuntimeError): diag.monitor(301, True)
            guard.assert_not_called()

    def test_trial_mailbox_selects_existing_b_and_crc_is_valid(self):
        words = trial.mailbox((0, 0, 1, 0, 0, 321, 10, 20, 195212, 0xfb8bac2e))
        self.assertEqual(words[:5], (0x584f424d, 1, 2, 1, 2))
        self.assertEqual(words[5:7], (195212, 0xfb8bac2e))
        self.assertEqual(words[7], zlib.crc32(struct.pack('<7I', *words[:7])))

    def test_incomplete_flash_blocks_trial(self):
        with self.assertRaises(RuntimeError): trial.validate_flash(bytes(16))

    def test_stale_down_notification_only_once_on_healthy_fd(self):
        interface = {'flags': ['UP'], 'mtu': 72, 'linkinfo': {'info_data': {
            'state': 'ERROR-ACTIVE', 'ctrlmode': ['FD'],
            'bittiming': {'bitrate': 500000}, 'data_bittiming': {'bitrate': 500000},
            'berr_counter': {'tx': 0, 'rx': 0}}, 'info_xstats': {}}}
        self.assertTrue(diag.healthy_setup_notification(interface, self.registers(), 0))
        self.assertFalse(diag.healthy_setup_notification(interface, self.registers(), 1))
        interface['flags'] = []
        self.assertFalse(diag.healthy_setup_notification(interface, self.registers(), 0))
        interface['flags'] = ['UP']
        self.assertFalse(diag.healthy_setup_notification(interface, self.registers(state=16), 0))
        interface['linkinfo']['info_data']['state'] = 'ERROR-WARNING'
        self.assertFalse(diag.healthy_setup_notification(interface, self.registers(), 0))


if __name__ == '__main__': unittest.main()
