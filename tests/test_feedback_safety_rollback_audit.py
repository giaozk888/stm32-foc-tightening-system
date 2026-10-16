import json
from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
import feedback_safety_rollback_audit as audit
import feedback_safety_commit as commit

class RollbackAuditTests(unittest.TestCase):
    def test_exact_failure_only(self):
        row=json.loads(audit.PRIOR.read_text('utf-8'))
        audit.prior_failure(row)
        for key,value in (('pass_',True),('motion_commands',True),
                          ('failure','different failure'),('force_confirm',True)):
            changed=dict(row); changed[key]=value
            with self.assertRaises(RuntimeError): audit.prior_failure(changed)
    def test_read_only_commands(self):
        c=audit.ReadConsole(None)
        for cmd in ('FW END','BENCH STOP','BENCH RUN','BENCH PROTECTION TEST TIMEOUT',
                    'START','RESET','FAULT CLEAR'):
            with self.assertRaises(ValueError): c.query(cmd)
            with self.assertRaises(ValueError): c.command(cmd)
        self.assertEqual(audit.READ,frozenset(('FW STATUS','BENCH STATUS','ANALOG SAFE STATUS')))
    def test_observation_includes_two_health_trials_and_boot_time(self):
        self.assertEqual(commit.OBSERVE_SECONDS,90)
        self.assertEqual(commit.OBSERVE_POLL_SECONDS,.2)
        self.assertLess(commit.OBSERVE_SECONDS,120)

if __name__ == '__main__': unittest.main()
