from pathlib import Path
import struct
import sys
import unittest
import zlib
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
import feedback_budget2x_acceptance as tool
import feedback_safety_commit as commit
import feedback_safety_stage as original
import feedback_safety_replay as replay

class DoubledBudgetAcceptanceTests(unittest.TestCase):
    def test_profile_commit_interface_and_staged_status(self):
        for name in ('IMAGE','SHA','OUTPUT','GEN','image','baseline','require_staged'):
            self.assertTrue(hasattr(tool,name),name)
        self.assertIs(tool.require_staged,original.require_staged)
        line=('OK FW CURRENT=A CONFIRMED=A PENDING=- ATTEMPTS=0 GEN=453 '
              'ACTIVE=1 TARGET=B RX=207088 SIZE=207088 EXPECT=0x7D85EA57')
        self.assertEqual(tool.require_staged(line,tool.GEN,tool.image())['GEN'],'453')
        for old,new in (('GEN=453','GEN=449'),('RX=207088','RX=207087'),
                        ('EXPECT=0x7D85EA57','EXPECT=0x6053B3A5')):
            with self.assertRaises(RuntimeError):
                tool.require_staged(line.replace(old,new),tool.GEN,tool.image())
    def test_closeout_is_read_only_and_does_not_upgrade_trial_result(self):
        src=(ROOT/'tools/feedback_budget2x_closeout.py').read_text('utf-8')
        for forbidden in ('FW END','BENCH STOP','TEST TIMEOUT',"'-rst'","'-w'"):
            self.assertNotIn(forbidden,src)
        self.assertIn('prior_trial_pass=False',src)
        self.assertIn("compare_flash(original,backup.read_bytes(),profile.image(),'B')",src)
        self.assertIn("row['fw']['GEN']!='457'",src)
    def test_exact_new_identity_not_historical_mutation(self):
        self.assertEqual(len(tool.image()),207088)
        self.assertEqual(tool.REPAIR_BUDGET,(6,4))
        self.assertEqual((original.GEN,len(original.image())),(449,207024))
        self.assertEqual(commit.main.__defaults__,(original,))
    def test_exact_rejected_baseline_and_other_states_rejected(self):
        raw=bytearray(b'\xff'*0x80000)
        a=(ROOT/'foc2_app_a/build/CurrentObserveOnly20261013/foc2.bin').read_bytes()
        b=original.image()
        raw[0x8000:0x8000+len(a)]=a; raw[0x40000:0x40000+len(b)]=b
        def meta(current=1,pending=0,attempts=0,generation=453,b_len=0):
            payload=struct.pack('<11I',0x424f4f54,3,current,pending,attempts,generation,
                                len(a),zlib.crc32(a),b_len,0,0)
            raw[0x7f000:0x7f030]=payload+struct.pack('<I',zlib.crc32(payload))
        meta(); self.assertEqual(tool.baseline_identity(raw)['generation'],453)
        for change in ({'current':2},{'pending':2},{'attempts':1},{'generation':449},{'b_len':207024}):
            meta(**change)
            with self.assertRaises(RuntimeError): tool.baseline_identity(raw)
        meta(); raw[0x8000+100]^=1
        with self.assertRaises(RuntimeError): tool.baseline_identity(raw)
    def test_readback_must_report_new_budget(self):
        line='OK HARD_OFF=1 MOTOR_QUALIFIED=0 RAW=VALIDITY_ONLY FILTERED=2_OF_3 GUARD_US=25 STATE=0 REASON=0 FLAGS=0 ARMED=1 ZERO=1 REPAIR_MAX=6 STREAK_MAX=4'
        commit.protection(line,repair_budget=tool.REPAIR_BUDGET)
        for old,new in (('REPAIR_MAX=6','REPAIR_MAX=3'),('STREAK_MAX=4','STREAK_MAX=2')):
            with self.assertRaises(RuntimeError): commit.protection(line.replace(old,new),repair_budget=tool.REPAIR_BUDGET)
    def test_no_new_actuation_and_private_reference_comparison(self):
        src=Path(tool.__file__).read_text('utf-8')
        self.assertIn('raw!=path.read_bytes()',src)
        self.assertIn("mode=='stage': stage_tool.main(profile)",src)
        self.assertNotIn("'START'",src)
        self.assertNotIn("'-w'",src)
    def test_replay_new_budget_without_mutating_historical_default(self):
        replay.compile_kernel(replay.EXE_2X,tool.REPAIR_BUDGET)
        samples=[[1600,1600] for _ in range(80)]
        for i in (2,5,8,11,14,17): samples[i]=[0,1600]
        row=replay.replay(samples,(1600,1600),replay.EXE_2X)
        self.assertEqual((row['reason'],row['repaired'],row['consumed']),(0,6,77))
        self.assertEqual((row['repair_window_max'],row['repair_streak_max']),(6,4))
        samples[20]=[0,1600]
        row=replay.replay(samples,(1600,1600),replay.EXE_2X)
        self.assertEqual((row['reason'],row['repaired'],row['trip_seq']),(9,7,22))
        self.assertFalse(row['motor_qualified'])

if __name__=='__main__': unittest.main()
