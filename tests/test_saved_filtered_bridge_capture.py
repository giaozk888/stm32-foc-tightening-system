"""Read saved evidence and replay locally; never opens a serial/debug port."""
from pathlib import Path
import json
import sys
import unittest
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
import filtered_bridge_acceptance as host
CAPTURE=ROOT/'safety_backups/filtered-bridge-live-20261013/capture-1791896441437660100.json'
DEPLOY=ROOT/'safety_backups/filtered-bridge-live-20261013/deploy-1791896083636506100.json'
class SavedBridgeTests(unittest.TestCase):
    def test_deployment_and_safe_closeout(self):
        row=json.loads(DEPLOY.read_text('utf-8'))
        self.assertTrue(row['pass_'] and row['final_safe_locked'])
        self.assertEqual(row['image_sha256'],host.SHA)
        self.assertEqual(row['final_fw']['GEN'],'463')
        self.assertEqual(row['final_fw']['CURRENT'],'B')
        self.assertFalse(row['bridge_start_sent'])
        host.filtered_guard_result(row['filtered_guard_line'])
        self.assertTrue(row['final_flash']['all_protected_regions_unchanged'])
    def test_timed_capture_and_identical_c_replay(self):
        row=json.loads(CAPTURE.read_text('utf-8'))
        self.assertTrue(row['pass_'] and row['final_safe_locked'] and row['bridge_observed'])
        self.assertTrue(row['all_flash_unchanged'])
        self.assertFalse(row['motor_qualified'])
        self.assertFalse(row['hardware_trip_timing_verified'])
        self.assertFalse(row['waveform_automatically_measured'])
        self.assertEqual(row['switch']['REASON'],'1')
        self.assertEqual(row['switch']['US'],'49976')
        self.assertEqual(row['feedback']['REPAIRED'],'13')
        self.assertEqual(row['feedback']['WORK_MAX_US'],'16')
        for k in ('SD','MOE','CCER','CEN'): self.assertEqual(row['switch'][k],'0')
        samples=row['samples']; self.assertEqual(len(samples),1000)
        gaps=[b[2]-a[2] for a,b in zip(samples,samples[1:])]
        self.assertTrue(all(0<gap<=75 for gap in gaps))
        self.assertNotEqual(len(set(gaps)),1) # measured timestamps, not synthetic 50us
        replay=host.replay(samples,tuple(map(int,row['switch']['ZERO'].split(','))),
                           int(row['bridge_supply']['VDDA_BOOT_MV']),row['feedback'])
        self.assertEqual(replay,row['replay'])
if __name__=='__main__': unittest.main()
