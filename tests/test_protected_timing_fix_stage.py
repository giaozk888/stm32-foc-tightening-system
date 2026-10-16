from pathlib import Path
import sys
import unittest
import tempfile
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
import protected_timing_fix_stage as fix

class TimingStageTests(unittest.TestCase):
    def test_exact_b(self):
        self.assertEqual(len(fix.pinned_image()),205200)
    def test_select_never_actuates_or_commits(self):
        class Port:
            def write(self,_): raise AssertionError('Hardware access forbidden')
        u=fix.SelectionConsole(Port())
        for command in ('FW END','FW CONFIRM','BOOT B','START','MOTOR TEST SPEED','MOTOR TEST STOP'):
            with self.subTest(command=command),self.assertRaises(ValueError): u.query(command)
        u.selections=1
        with self.assertRaises(ValueError): u.query('BOOT A')
    def test_only_one_metadata_selection_allowed(self):
        raw=bytes(0x80000)
        prior=(0x424F4F54,3,2,0,0,473,210280,123,205152,456,0,789)
        selected=(0x424F4F54,3,1,0,0,474,210280,123,205152,456,0,999)
        with patch.object(fix,'latest_meta',side_effect=[prior,selected]):
            self.assertEqual(fix.check_selected(raw,raw),474)
        for idx,val in ((1,2),(2,2),(3,2),(4,1),(5,475),(6,1),(8,1),(10,1)):
            bad=list(selected);bad[idx]=val
            with self.subTest(idx=idx),patch.object(fix,'latest_meta',side_effect=[prior,tuple(bad)]),self.assertRaises(RuntimeError):
                fix.check_selected(raw,raw)
        for offset in (0,0x8000,0x40000,0x78000,0x7F800):
            changed=bytearray(raw);changed[offset]=1
            with self.subTest(offset=offset),self.assertRaises(RuntimeError):
                fix.check_selected(bytes(changed),raw)
    def test_new_acceptance_keeps_old_evidence_pins(self):
        # An old historical stage may never become a timing-fix stage merely
        # because a caller chooses the new profile.
        with tempfile.TemporaryDirectory() as directory:
            import json
            receipt=Path(directory)/'stage.json'
            receipt.write_text(json.dumps(dict(pass_=True,mode='stage',
                image_sha256=fix.old.SHA,all_bytes_outside_b_unchanged=True)),'utf-8')
            with patch.object(fix,'OUTPUT',Path(directory)),self.assertRaises(RuntimeError):
                fix.acceptance.stage_evidence(receipt,b'new',source_profile=fix)

if __name__=='__main__': unittest.main()
