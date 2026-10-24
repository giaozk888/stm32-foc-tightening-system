import hashlib
import json
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
import mechanical_encoder_fix_remaining as rem
low=rem.low


class RemainingTests(unittest.TestCase):
    def test_saved_restore_and_default_are_files_only(self):
        p=subprocess.run([sys.executable,str(ROOT/'tools/mechanical_encoder_fix_remaining.py')],
            cwd=ROOT,capture_output=True,text=True)
        self.assertEqual(p.returncode,0,p.stdout+p.stderr)
        self.assertIn('8 mechanical points; no devices',p.stdout)
        r=json.loads(rem.ROOT_RESTORE.read_text())
        self.assertTrue(r['pass_']);self.assertTrue(r['all_app_private_unchanged'])
        self.assertTrue(r['b_application_not_run']);self.assertEqual(r['metadata'][8:10],[227964,627317606])

    def test_power_gates_before_setup_and_exact_order(self):
        with patch.multiple(low,setup=low.setup,POINTS=low.POINTS,TRIP_RPM=low.TRIP_RPM,
            TRAVEL_DEG=low.TRAVEL_DEG,CLOSURE_SECONDS=low.CLOSURE_SECONDS,
            LIMITS_QUERY=low.LIMITS_QUERY,LIMITS_EXTRA=low.LIMITS_EXTRA),\
             patch.object(rem,'ORIGINAL_SETUP') as setup:
            for args in (['--prepare-off'],['--execute-eight','missing'],['--restore-b-drive-off','missing']):
                with self.assertRaises(SystemExit):rem.main(args)
            setup.assert_not_called()
        self.assertEqual(rem.POINTS,(600,600,700,700,700,800,800,800))

    def test_existing_proof_never_programs_or_activates(self):
        before=b'\0'*0x8000+b'image'
        row=dict(physical_power_off=True)
        with patch.object(low.base,'baseline',return_value=before),patch.object(Path,'read_bytes',return_value=before),\
             patch.object(low.base.hw,'debug',return_value='off') as debug,\
             patch.object(low.base.hw,'check_off',return_value=dict(VTOR=0x08040000,SD=0,BDTR=0,CCER=0)):
            rem.verify_existing_off(row,'unit',b'image')
        commands=[c for call in debug.call_args_list for c in call.args[1]]
        for token in ('flash write','flash erase','reset run','write_image','load_image'):
            self.assertFalse(any(token in c for c in commands),token)
        self.assertEqual(debug.call_count,2)
        self.assertFalse(row['flash_programming']);self.assertFalse(row['activation'])
        self.assertEqual(row['motor_commands'],0);self.assertTrue(row['read_only_existing_verified_off'])
        with self.assertRaises(ValueError):rem.verify_existing_off({},'unit',b'image')

    def test_readiness_identity_and_tampering(self):
        before=b'\0'*0x8000+b'image';capture=low.TMP/'unit-existing-off.bin'
        second=low.TMP/'unit-independent-off.bin';path=low.TMP/'unit-stage.json'
        baseline=rem.ROOT_RESTORE.resolve()
        good=dict(mode='stage',image_sha256=rem.fixed.SHA,elf_sha256=rem.fixed.ELF_SHA,
            speeds_rpm=list(rem.POINTS),ka_a_per_rpm_s=low.KA,overspeed_trip_rpm=1000,travel_limit_deg=30000,
            staged_capture=str(capture),independent_capture=str(second),
            staged_sha256=hashlib.sha256(before).hexdigest(),baseline_restore_receipt=str(baseline),
            activation=False,flash_programming=False,motor_commands=0,
            pass_=True,physical_power_off=True,read_only_existing_verified_off=True,
            independent_readback_pass=True,final_outputs_off=True,final_cpu_halted=True)
        with patch.object(low.base,'BASE_RESTORE_RECEIPT',baseline),\
             patch.object(low.base,'baseline',return_value=before),patch.object(Path,'read_bytes',return_value=before):
            with patch.object(Path,'read_text',return_value=json.dumps(good)):
                self.assertEqual(rem.staged(path,b'image')[1],before)
            for key,bad in [('speeds_rpm',[800]),('flash_programming',True),('image_sha256','bad'),
                ('physical_power_off',False),('activation',True),('final_outputs_off',False),
                ('independent_readback_pass',False),('staged_sha256','bad')]:
                r={**good,key:bad}
                with patch.object(Path,'read_text',return_value=json.dumps(r)):
                    with self.assertRaises(ValueError,msg=key):rem.staged(path,b'image')


if __name__=='__main__':unittest.main()
