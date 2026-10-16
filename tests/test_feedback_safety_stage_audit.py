from pathlib import Path
import sys
import unittest
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
import feedback_safety_stage_audit as tool

class StageAuditTests(unittest.TestCase):
    def test_exact_failure_only(self):
        row=dict(pass_=False,failure='95253 ERR 101 FW_UPDATE_ACTIVE',image_sha256=tool.staging.SHA,
                 fw_end=False,resets=0,activation=False,all_bytes_outside_b_unchanged=True,
                 protected_flash=dict(all_protected_regions_unchanged=True))
        tool.prior_evidence(row)
        for key,value in (('pass_',True),('failure','Transfer failed'),('resets',1),
                          ('all_bytes_outside_b_unchanged',False),('image_sha256','0'*64)):
            bad=dict(row); bad[key]=value
            with self.assertRaises(RuntimeError): tool.prior_evidence(bad)

    def test_no_mutation_commands_or_original_overwrite(self):
        src=Path(tool.__file__).read_text('utf-8')
        self.assertNotIn('PRIOR.write',src)
        self.assertNotIn('stage(uart',src)
        self.assertNotIn("command('FW END'",src)
        self.assertNotIn("query('BENCH",src)
        self.assertNotIn("query('ANALOG SAFE",src)
        self.assertIn("tokens[0] not in ('-u','-r32')",src)

if __name__=='__main__': unittest.main()
