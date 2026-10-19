"""Pinned positive-only 200mA runner; all tests are files/mocks only."""
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
import test_torque_chain_acceptance as legacy_tests
from test_torque_chain_200ma import capture200

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
import torque_chain_200ma_acceptance as runner


class Torque200AcceptanceTests(legacy_tests.TorqueAcceptanceTests):
    def setUp(self):
        binding=patch.object(legacy_tests,'runner',runner); binding.start()
        self.addCleanup(binding.stop)

    def test_exact_image_and_preserved_baseline(self):
        self.assertEqual(len(runner.image()),229004)
        self.assertEqual(runner.old.zero.latest_meta(runner.baseline())[2:6],(2,0,0,685))
        with patch.object(runner,'IMAGE',runner.previous.IMAGE):
            with self.assertRaises(ValueError): runner.image()

    def test_signed_ref_and_profile_must_be_200ma_not_100(self):
        data=capture200([i*.1 for i in range(12)])
        for i in range(12):
            values=list(runner.decoder.startup.FRAME.unpack_from(data,i*124))
            values[39]=3; values[40]=3
            runner.decoder.startup.FRAME.pack_into(data,i*124,*values)
        meta=dict(iq_mA=200,sign=1,offset_electrical_deg=0,used=1,queued=0,active=0,admitting=0,denied=0)
        row=dict(pulse_attempts=1,postflight_state=dict(STATE='3'),
            snapshot=dict(first_fault=dict(valid=0),timing=dict(wall_max_us=30,deadline_miss=0,
                actual_late_count=0,actual_margin_min_us=12)),final_cpu_halted=True,
            final_outputs_off=True,all_app_private_unchanged=True)
        with patch.object(runner.decoder,'metadata',return_value=meta), \
             patch.object(runner.decoder.startup,'extract',return_value=data):
            runner.classify(row,b''); self.assertTrue(row['pass_'])
            self.assertEqual(row['torque_diagnostic']['Iq_command_A'],.2)
            self.assertFalse(row['mechanical_direction_verified'])
            with self.assertRaises(ValueError): runner.classify(row,b'',expected_sign=-1)
            # Even a claimed 200mA metadata tag cannot relabel a 100mA drive.
            values=list(runner.decoder.startup.FRAME.unpack_from(data,0)); values[10]=.1
            runner.decoder.startup.FRAME.pack_into(data,0,*values)
            runner.classify(row,b''); self.assertFalse(row['pass_'])
            meta['iq_mA']=100
            with self.assertRaises(ValueError): runner.classify(row,b'')

    def test_preflight_refuses_wrong_amplitude_before_pulse(self):
        from unittest.mock import Mock
        uart=Mock()
        uart.query.side_effect=['zero','profile','fw']
        with patch.object(runner.old.zero,'zero_fields',return_value={}), \
             patch.object(runner,'fields',side_effect=[
                 dict(NAME='PROTECTED_PIPELINE_CLOSED_LOOP',HARD_OFF='0',FSM='ORIGINAL',
                      PIPELINE='1',RPM='20',LEASE_US='200000',SPEED_CTRL='SB3',VLIMIT_MV='1600'),
                 dict(CURRENT='A',CONFIRMED='A',PENDING='-',ATTEMPTS='0',ACTIVE='0'),
                 dict(IQ_MA='100',ID_MA='0',LEASE_US='200000',PERIOD_US='8000',USED='0',ACTIVE='0',DENIED='0')]), \
             patch.object(runner.old.prior,'wait_timing') as timing:
            with self.assertRaisesRegex(RuntimeError,'unused/ready'): runner.preflight(uart,{})
            timing.assert_not_called()
            uart.torque.assert_called_once_with('MOTOR TEST TORQUE STATUS')


if __name__=='__main__': unittest.main()
