from pathlib import Path
import sys
import unittest
from unittest.mock import patch
import json
import tempfile
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
import protected_closed_loop_acceptance as accept
import protected_closed_loop_stage as staging
import protected_closed_loop_recover as recovery

class RunnerTests(unittest.TestCase):
    def test_readiness_is_not_trial_completion(self):
        good='OK STATE=1 USED=0 QUEUED=0 ARMED=1 ZERO=3 FLAGS=0 FAULT=0 SD=0 MOE=0 CCER=0 QUALIFIED=0'
        self.assertEqual(accept.protected_state(good,ready=True)['STATE'],'1')
        for field in ('STATE=1','USED=0','QUEUED=0','ARMED=1','ZERO=3','FLAGS=0','FAULT=0','SD=0','MOE=0','CCER=0'):
            changed=good.replace(field,field.split('=')[0]+'=9')
            with self.subTest(field=field),self.assertRaises(RuntimeError):
                accept.protected_state(changed,ready=True)
    def test_guard_and_work_counts_required(self):
        good='OK CLOCK_HZ=1000000 WORK=2000 MAX_US=32 LATE=0 IRQ=6000 OUTER=200 LEASE_US=400000 SAMPLE_US=100 OUTER_US=2000'
        accept.timing(good)
        for a,b in (('MAX_US=32','MAX_US=50'),('LATE=0','LATE=1'),('OUTER=200','OUTER=0'),('IRQ=6000','IRQ=0')):
            with self.subTest(a=a),self.assertRaises(RuntimeError): accept.timing(good.replace(a,b))
    def test_protection_not_bypassed(self):
        good='OK FILTER=TREND4 OC=2_OF_3 TRIP_MA=4000 STATE=0 REASON=0 FLAGS=0 BUDGET=6 STREAK=4'
        accept.protection(good)
        with self.assertRaises(RuntimeError): accept.protection(good.replace('STATE=0','STATE=2'))
    def test_stage_rejects_activation_before_uart(self):
        class Port:
            def write(self,_): raise AssertionError('No hardware access')
        with self.assertRaises(ValueError): staging.Console(Port()).command('FW END')
        with self.assertRaises(ValueError): accept.Console(Port()).query('START')
        with self.assertRaises(ValueError): accept.Console(Port()).query('FW CONFIRM')
        u=accept.Console(Port());u.starts=1;u.ends=1
        for cmd in ('MOTOR TEST SPEED','FW END'):
            with self.assertRaises(ValueError): u.query(cmd)
    def test_staged_b_hash_matches_offline_artifact(self):
        self.assertEqual(len(staging.pinned_image()),205152)
    def test_bootloader_rollback_invalidates_failed_slot_metadata(self):
        before=bytes(0x80000);staged=before;image=b'initial'
        old=(0,3,1,0,0,466,210280,123,42,456,0,0)
        rolled=(0,3,1,0,0,470,210280,123,0,0,0,0)
        with patch.object(recovery,'latest_meta',side_effect=[old,rolled]):
            self.assertEqual(recovery.check_failed_chain(before,before,staged,image,True)[5],470)
        for idx,val in ((2,2),(3,2),(4,1),(5,471),(6,1),(8,42)):
            bad=list(rolled);bad[idx]=val
            with patch.object(recovery,'latest_meta',side_effect=[old,tuple(bad)]),self.assertRaises(RuntimeError):
                recovery.check_failed_chain(before,before,staged,image,True)
        badraw=bytearray(before);badraw[0x8000]=1
        with self.assertRaises(RuntimeError):
            recovery.check_failed_chain(bytes(badraw),before,staged,image,True)
    def test_prestart_resume_never_retries_motion_or_activation(self):
        with tempfile.TemporaryDirectory() as directory:
            base=Path(directory);receipt=base/'trial.json';stage=base/'stage.json'
            good=dict(image_sha256=staging.SHA,stage=str(stage),host_motor_commands=0,
                host_trial_commits=1,failure='No ACK, never resend: MOTOR TEST STATUS',
                before_trial_backup=str(base/'private/before.bin'),
                uart=['BOOT HEALTH: CONFIRM REQUESTED SLOT=B -> RESETTING'])
            with patch.object(staging,'OUTPUT',base),patch.object(Path,'read_text',return_value=json.dumps(good)),\
                patch.object(Path,'read_bytes',return_value=b'staged'):
                accept.prestart_resume_evidence(receipt,stage,b'staged')
            for key,value in (('host_motor_commands',1),('host_trial_commits',2),
                ('failure','Startup latched fault; no motor command'),('start_ack','QUEUED=1'),
                ('confirmed',{'CURRENT':'B'}),('uart',[])):
                bad=dict(good);bad[key]=value
                with self.subTest(key=key),patch.object(staging,'OUTPUT',base),\
                    patch.object(Path,'read_text',return_value=json.dumps(bad)),\
                    self.assertRaises(RuntimeError):
                    accept.prestart_resume_evidence(receipt,stage,b'staged')

if __name__=='__main__': unittest.main()
