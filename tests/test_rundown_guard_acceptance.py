"""Mocked new-candidate acceptance; no board/serial/programming."""
import contextlib
import io
from pathlib import Path
import struct
import sys
import unittest
from unittest.mock import Mock,patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
import rundown_guard_acceptance as runner
from test_rundown_startup_decode import make_trace
from test_sb3_speed_acceptance import FullBoard


class AcceptanceTests(unittest.TestCase):
    def test_exact_new_image_and_preserved_B665(self):
        self.assertEqual(len(runner.image()),228220)
        self.assertEqual(runner.old.zero.latest_meta(runner.baseline())[2:6],(2,0,0,665))
        with patch.object(runner,'IMAGE',runner.previous.IMAGE):
            with self.assertRaises(ValueError): runner.image()

    def test_default_never_touches_devices_and_gates_before_image(self):
        with patch.object(sys,'argv',['rundown']),patch.object(runner,'debug') as debug, \
                patch.object(runner.old.prior,'open_port') as port,contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(runner.main(),0); debug.assert_not_called(); port.assert_not_called()
        for args in (['--stage-off'],['--execute-powered','x'],['--restore-b-drive-off','x']):
            with patch.object(sys,'argv',['rundown',*args]),patch.object(runner,'image') as image, \
                    contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit): runner.main()
                image.assert_not_called()

    def test_failed_preflight_never_starts_and_captures_matching_elf(self):
        port=Mock(); port.is_open=True; uart=Mock(); uart.lines=[]; row={}; before=runner.baseline()
        with patch.object(runner,'stage_receipt',return_value=(runner.BASE,before)), \
                patch.object(runner.old.prior,'open_port',return_value=port), \
                patch.object(runner.old.prior,'JournalConsole',return_value=uart), \
                patch.object(runner.old.prior,'checkpoint'),patch.object(runner,'debug'), \
                patch.object(runner.old.prior,'wait_health_confirmation',side_effect=RuntimeError('preflight')), \
                patch.object(runner.old.prior,'motion') as motion,patch.object(runner.old,'capture_stopped') as capture:
            with self.assertRaisesRegex(RuntimeError,'preflight'):
                runner.execute(row,'mock',runner.BASE,runner.image())
            motion.assert_not_called(); capture.assert_called_once_with(row,'mock',before,elf=runner.ELF)

    def classify(self,armed=0,contact=0,outcome=7,core_fault=0,stage=11,motion=False):
        table=runner.symbols(runner.ELF); ram=bytearray(0x20000)
        def set_word(name,value):
            address,size=table[name]; ram[address-0x20000000:address-0x20000000+size]=value.to_bytes(size,'little')
        for name,value in dict(tightening_last_outcome=outcome,tightening_contact_confirmed=contact,
                               tightening_test_stage=stage,foc_fault=core_fault).items(): set_word(name,value)
        address,size=table['cl_startup']; data=make_trace()
        if armed:
            for i in range(33): data[i*124+115]=1
        ram[address-0x20000000:address-0x20000000+size]=data
        struct.pack_into('<3If3Bx',ram,table['tightening_rundown'][0]-0x20000000,1500,0,500,0,armed,0,1)
        row=dict(motion_pass=motion,recipe_restored=True,safe=dict(LATCHED='1',SD='0',MOE='0',FOC='0'),
            snapshot=dict(first_fault=dict(valid=0 if motion else 1,domain=3,fault_reason=7),
                          timing=dict(wall_max_us=30,deadline_miss=0,actual_late_count=0,actual_margin_min_us=12)))
        runner.classify(row,ram)
        return row,ram

    def test_expected_no_rotation_guard_pass_is_not_motor_pass(self):
        row,_=self.classify()
        self.assertTrue(row['guard_pass']); self.assertTrue(row['no_rotation_protection_verified'])
        self.assertFalse(row['speed_tracking_pass']); self.assertFalse(row['pass_'])

    def test_false_contact_or_ok_without_arm_cannot_pass(self):
        for outcome,stage,contact in ((1,9,1),(0,2,1)):
            row,_=self.classify(outcome=outcome,stage=stage,contact=contact,motion=True)
            self.assertFalse(row['guard_pass']); self.assertFalse(row['pass_'])

    def test_speed_requires_arm_timing_and_clean_host_cleanup(self):
        row,ram=self.classify(armed=1,outcome=2,stage=9,motion=True)
        self.assertTrue(row['pass_'])
        row['snapshot']['timing']['deadline_miss']=1; runner.classify(row,ram)
        self.assertFalse(row['pass_'])
        row['snapshot']['timing']['deadline_miss']=0; row['motion_failure']='restore failed'
        runner.classify(row,ram); self.assertFalse(row['pass_'])

    def test_staging_rejects_changes_to_B_private_or_metadata(self):
        before=runner.baseline(); data=runner.image(); end=(0x8000+len(data)+0x7ff)&~0x7ff
        raw=bytearray(before); raw[0x8000:end]=data+b'\xff'*(end-0x8000-len(data))
        runner.old.zero.validate_staged(raw,before,data)
        for offset in (0,0x40000,0x7e800,0x7f800):
            bad=raw.copy(); bad[offset]^=1
            with self.assertRaises(ValueError): runner.old.zero.validate_staged(bad,before,data)

    def run_full(self,board):
        clock=iter(i*.01 for i in range(20000)); row=dict(samples=[],postflight={})
        fsm=runner.previous.voltage.cycle.fsm
        with patch.object(fsm,'require_idle_ready'),patch.object(fsm.time,'monotonic',side_effect=lambda:next(clock)), \
                patch.object(fsm,'stop',side_effect=lambda b:b.command('STOP')),contextlib.redirect_stdout(io.StringIO()):
            runner.motion(board,row,full_fsm=True)
        return row

    def test_full_original_fsm_does_not_stop_after_two_seconds_or_contact(self):
        board=FullBoard([1,2,3,4,5,6,7,9]); row=self.run_full(board)
        self.assertTrue(row['cycle_pass']); self.assertEqual(row['stages'],[1,2,3,4,5,6,7,9])
        self.assertEqual(board.commands.count('START'),1); self.assertIn('ANALOG SAFE',board.commands)
        self.assertTrue(row['recipe_restored']); self.assertNotIn('SAVE',board.commands)

    def test_full_fault_never_retries(self):
        board=FullBoard([1],fault=True)
        with self.assertRaisesRegex(RuntimeError,'Fault during cycle'): self.run_full(board)
        self.assertEqual(board.commands.count('START'),1); self.assertIn('STOP',board.commands)

    def test_full_mode_needs_power_assertion(self):
        for args in (['--full-state-machine'],['--execute-powered','x','--full-state-machine']):
            with patch.object(sys,'argv',['rundown',*args]),patch.object(runner,'image') as image, \
                    contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit): runner.main()
                image.assert_not_called()

    def test_confirmed_prestart_resume_rejects_ambiguous_start(self):
        path=runner.TMP/'rundown-guard-run-1792323719565462200.json'
        r=runner.json.loads(path.read_text('utf-8'))
        self.assertEqual(runner.resume_receipt(path,runner.image())[0].name,
                         'rundown-guard-run-1792323719565462200-flash.bin')
        for changed in ({'start_attempts':1},{'failure':'motor fault'},
                        {'commands':[{'command':'START'}]},{'normally_confirmed':False}):
            with patch.object(Path,'read_text',return_value=runner.json.dumps(dict(r,**changed))):
                with self.assertRaises(ValueError): runner.resume_receipt(path,runner.image())


if __name__=='__main__': unittest.main()
