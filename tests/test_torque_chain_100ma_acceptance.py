"""Same single-pulse interlocks, now bound to exact 100mA A and preserved B673."""
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
import test_torque_chain_acceptance as legacy_tests

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
import torque_chain_100ma_acceptance as runner
from test_torque_chain_100ma import capture


class Torque100AcceptanceTests(legacy_tests.TorqueAcceptanceTests):
    def setUp(self):
        self.binding=patch.object(legacy_tests,'runner',runner); self.binding.start()
        self.addCleanup(self.binding.stop)

    def test_exact_image_and_preserved_baseline(self):
        self.assertEqual(len(runner.image()),229044)
        self.assertEqual(runner.old.zero.latest_meta(runner.baseline())[2:6],(2,0,0,673))
        with patch.object(runner,'IMAGE',runner.previous.IMAGE):
            with self.assertRaises(ValueError): runner.image()

    def test_classification_requires_100ma_and_real_IQ_drive_rows(self):
        data=capture([i*.1 for i in range(12)],1)
        for i in range(12):
            values=list(runner.decoder.startup.FRAME.unpack_from(data,i*124))
            values[39]=3; values[40]=3
            runner.decoder.startup.FRAME.pack_into(data,i*124,*values)
        meta=dict(iq_mA=100,sign=1,offset_electrical_deg=0,used=1,queued=0,active=0,admitting=0,denied=0)
        row=dict(pulse_attempts=1,postflight_state=dict(STATE='3'),
            snapshot=dict(first_fault=dict(valid=0),timing=dict(wall_max_us=30,deadline_miss=0,
                actual_late_count=0,actual_margin_min_us=12)),final_cpu_halted=True,
            final_outputs_off=True,all_app_private_unchanged=True)
        with patch.object(runner.decoder,'metadata',return_value=meta), \
             patch.object(runner.decoder.startup,'extract',return_value=data):
            runner.classify(row,b''); self.assertTrue(row['pass_'])
            self.assertEqual(row['torque_diagnostic']['Iq_command_A'],.1)
            self.assertFalse(row['mechanical_direction_verified'])
            row['stop_error']='missing stop ack'; runner.classify(row,b''); self.assertFalse(row['pass_'])
            meta['iq_mA']=50
            with self.assertRaises(ValueError): runner.classify(row,b'')


if __name__=='__main__': unittest.main()
