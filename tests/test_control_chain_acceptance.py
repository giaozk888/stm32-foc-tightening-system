"""Offline deployment identity, command scope and no-resend contracts."""
import sys
from pathlib import Path
import unittest
import struct
import zlib
import json
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'tools'))
import control_chain_reconnect_acceptance as live
import control_chain_timeout_acceptance as timeout_live

class Port:
    def __init__(self): self.writes = []
    def write(self, data): self.writes.append(data)

class AcceptanceTests(unittest.TestCase):
    def test_exact_hard_off_a(self):
        self.assertEqual(live.image_info(live.image())[0], 'A')
        self.assertEqual(len(live.image()), 210280)
    def test_stage_forbids_activation_and_bench_start(self):
        uart = live.Console(Port())
        for text in ('FW END', 'START', 'BENCH CHAIN TIGHTEN', 'SWITCH START FILTERED_BRIDGE', 'RESET'):
            with self.assertRaises(ValueError):
                if text == 'FW END': uart.command(text)
                else: uart.query(text)
        self.assertEqual(uart.port.writes, [])
    def test_commit_forbids_programming_and_real_power_commands(self):
        uart = live.Console(Port(), commit=True)
        for text in ('FW BEGIN 210280 ABCD1234', 'XFER ENGINE CLOSE'):
            with self.assertRaises(ValueError): uart.command(text)
        for text in ('START', 'BENCH RUN', 'BENCH CHAIN SPEED', 'ANALOG SAFE CLEAR', 'SWITCH START FILTERED_BRIDGE'):
            with self.assertRaises(ValueError): uart.query(text)
    def test_unknown_ack_never_resends_test(self):
        uart = live.Console(Port(), commit=True)
        uart.read_line = lambda timeout: None
        with self.assertRaises(TimeoutError): uart.query('BENCH CHAIN TIGHTEN', timeout=0)
        with self.assertRaises(ValueError): uart.query('BENCH CHAIN TIGHTEN', timeout=0)
        self.assertEqual(len(uart.port.writes), 1)
    def test_commit_single_attempt(self):
        uart = live.Console(Port(), commit=True)
        uart.read_line = lambda timeout: None
        with self.assertRaises(TimeoutError): uart.command('FW END', timeout=0)
        with self.assertRaises(ValueError): uart.command('FW END', timeout=0)
        self.assertEqual(len(uart.port.writes), 1)
    def test_existing_trial_is_only_start_trial_magic_last_and_reset(self):
        data = live.image()
        command = live.trial_request(data, 'OK FW CURRENT=B TARGET=A CONFIRMED=B PENDING=- ATTEMPTS=0 ACTIVE=0 GEN=463')
        self.assertEqual(command[:5], ('-w32','0x2001FFC0','0','-w32','0x2001FFC4'))
        words = (int(command[-2],16), *map(lambda v:int(v,16), command[5:12]))
        self.assertEqual(words[:7], (0x584F424D,1,2,2,1,len(data),zlib.crc32(data)))
        self.assertEqual(words[7],zlib.crc32(struct.pack('<7I',*words[:7])))
        self.assertEqual(command[-4:-2], ('-w32','0x2001FFC0'))
        self.assertEqual(command[-1],'-rst')
    def test_existing_trial_rejects_pending_or_wrong_generation(self):
        for fw in ('OK FW CURRENT=B TARGET=A CONFIRMED=B PENDING=A ATTEMPTS=2 ACTIVE=0 GEN=464',
                   'OK FW CURRENT=B TARGET=A CONFIRMED=B PENDING=- ATTEMPTS=0 ACTIVE=0 GEN=467',
                   'OK FW CURRENT=B TARGET=A CONFIRMED=B PENDING=- ATTEMPTS=0 ACTIVE=1 GEN=463'):
            with self.assertRaises(RuntimeError): live.trial_request(live.image(),fw)
    def test_saved_real_spd_and_iq_cycle_is_not_rerun_for_host_typo(self):
        row=json.loads((ROOT/'safety_backups/control-chain-live-20261013/trial-existing-1791939137274139900.json').read_text('utf-8'))
        result=live.original_chain_result(row['chain_observations'],row['chain_final'])
        self.assertTrue(result['control_chain_pass'])
        self.assertFalse(result['motor_qualified'])
        self.assertEqual(result['current_loop_count'],56528)
        bad=[dict(s,status=s['status'].replace('MODE=SPD','MODE=UNKNOWN')) for s in row['chain_observations']]
        with self.assertRaises(RuntimeError): live.original_chain_result(bad,row['chain_final'])
    def test_missing_iq_stages_cannot_be_claimed_complete(self):
        row=json.loads((ROOT/'safety_backups/control-chain-live-20261013/trial-existing-1791939137274139900.json').read_text('utf-8'))
        bad=[s for s in row['chain_observations'] if 'MODE=IQ' not in s['status']]
        with self.assertRaises(RuntimeError): live.original_chain_result(bad,row['chain_final'])
    def test_timeout_only_runner_does_not_allow_motion_or_firmware_commands(self):
        u = timeout_live.Console(Port())
        for text in ('FW END','FW BEGIN 210280 ABCD1234','XFER ENGINE CLOSE'):
            with self.assertRaises(ValueError): u.command(text)
        for text in ('START','BENCH CHAIN TIGHTEN','BENCH RUN','SWITCH START FILTERED_BRIDGE','ANALOG SAFE CLEAR'):
            with self.assertRaises(ValueError): u.query(text)
        self.assertEqual(u.port.writes,[])
    def test_timeout_only_runner_pins_confirmed_a466(self):
        good='OK FW CURRENT=A CONFIRMED=A TARGET=B PENDING=- ATTEMPTS=0 ACTIVE=0 GEN=466'
        self.assertEqual(timeout_live.require_a466(good)['GEN'],'466')
        for bad in (good.replace('GEN=466','GEN=467'),good.replace('PENDING=-','PENDING=B')):
            with self.assertRaises(RuntimeError): timeout_live.require_a466(bad)

if __name__ == '__main__': unittest.main()
