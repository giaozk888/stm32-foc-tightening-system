"""Pinned board runner/decoder tests: never touch serial, USB or debugger."""
import struct
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
import preempt_commit_board_test as board
import preempt_commit_report as report

class BoardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): board.configure()

    def test_pinned_image_schema_and_console(self):
        self.assertEqual(len(board.image()),228524)
        board.confirm.layout()
        self.assertEqual(board.confirm.ram_symbol('foc_preempt_timing')[1],140)
        console=object.__new__(board.prior.Console)
        for text in ('START','MOTOR TEST START','FW END','FW CONFIRM','RESET','MOTOR TEST CLEAR'):
            with self.assertRaises(ValueError): console.query(text)

    def test_stage_boundaries_and_metadata(self):
        row=__import__('json').loads(board.BASE_RECEIPT.read_text())
        self.assertEqual(row['final_sha256'],board.BASE_SHA)
        self.assertEqual(tuple(row['final_metadata']),board.BASE_META)
        commands=board.tx.stage_commands(Path('live.bin'),Path('expected.bin'),Path('stage.bin'))
        text='\n'.join(commands)
        self.assertIn('0x08008000 bin',text)
        self.assertIn('verify_image',text)
        for forbidden in ('reset run','resume','mww 0x2001FFC0'):
            self.assertNotIn(forbidden,text)

    def test_cli_power_gate_before_devices(self):
        for mode in ('--stage-inactive-a','--trial-from-stage','--restore-from-trial'):
            args=[mode]+([] if mode=='--stage-inactive-a' else ['unused.json'])
            p=subprocess.run([sys.executable,str(board.ROOT/'tools/preempt_commit_board_test.py'),*args],
                             capture_output=True,text=True)
            self.assertNotEqual(p.returncode,0)
            self.assertIn('disconnected motor required',p.stderr)

    def test_same_cycle_accounting_and_capture_ownership(self):
        ram=bytearray(0x20000); flash=bytearray(0x80000)
        data=board.image(); flash[0x8000:0x8000+len(data)]=data
        sym=report.schema.symbols(board.ELF)
        def put(name,words):
            addr,size=sym[name]; self.assertEqual(size,len(words)*4)
            struct.pack_into('<'+'I'*len(words),ram,addr-0x20000000,*words)
        f=[10103,3860,6243,583,600,2677,0,1,1,2,0,1,2,1]
        put('foc_preempt_timing',[42,0,10103,3860,6243,1,200]+f+f)
        put('foc_probe_priorities_ok',[1])
        put('foc_probe_irq_priority',[0,1,1,1,2,15,15])
        p=report.decode(board.ELF,bytes(ram),bytes(flash),0x08008000)
        miss=p['timing']['first_miss']
        self.assertTrue(miss['valid']); self.assertEqual(miss['dominant'],'DMA1_CH4_RX')
        self.assertEqual(miss['wall_cycles'],miss['preempt_cycles']+miss['active_est_cycles'])
        self.assertIsNone(p['actual_ccr']['pwm_update_margin_us_min'])
        self.assertIn('NO_VALID_ACTUAL',p['pwm_verdict'])
        for vtor in (0,0x08040000):
            with self.assertRaises(ValueError): report.decode(board.ELF,ram,flash,vtor)
        flash[0x8100]^=1
        with self.assertRaises(ValueError): report.decode(board.ELF,ram,flash,0x08008000)
        f[2]+=1
        with self.assertRaises(ValueError): report.frame(f)

    def test_hash_fail_closed(self):
        with patch.object(board,'SHA','0'*64):
            with self.assertRaises(ValueError): board.image()

if __name__=='__main__': unittest.main()
