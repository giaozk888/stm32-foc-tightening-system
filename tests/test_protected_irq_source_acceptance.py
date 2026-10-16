import json
import unittest
from unittest.mock import patch
import protected_irq_source_stage as stage
import protected_irq_source_acceptance as acceptance

class SourceAcceptanceTests(unittest.TestCase):
    def test_exact_image_and_a510_identity(self):
        self.assertEqual(len(stage.pinned_image()),206520)
        r=json.loads(stage.FAILURE.read_text('utf-8')); raw=bytes(0x80000)
        with patch.object(stage.previous.board_profile.previous,'private_capture',return_value=raw), \
             patch.object(stage,'latest_meta',return_value=(0,0,1,0,0,510,123,456,0,0)):
            self.assertEqual(stage.verified_baseline(raw,stage.FAILURE),510)
            with self.assertRaises(RuntimeError): stage.verified_baseline(b'1'+raw[1:],stage.FAILURE)
        for key,value in (('pass_',False),('fallback_fault',True),('resets',1),
                          ('motor_commands',1),('image_sha256','wrong'),('fw',{'GEN':'506'})):
            bad=r.copy(); bad[key]=value
            with patch.object(stage.Path,'read_text',return_value=json.dumps(bad)):
                with self.assertRaises(RuntimeError): stage.verified_baseline(raw,stage.FAILURE)

    def test_invalid_or_late_source_evidence_rejected(self):
        row=dict(irq_frame=dict(ERR='0',ORDER='G,T,R,X',BODY='EXCL',VALID='0'),
            irq_stats=dict(ERR='0',ORDER='G,T,R,X',MAX='BODY_INCL',CNT='1001,1,1,1',MAX_CYC='10,20,30,40'),
            irq_total=dict(ERR='0',ORDER='G,T,R,X',BODY='EXCL',CYC='10000,20,30,40'))
        acceptance.validate_sources(row)
        for key,field,value in (('irq_frame','ERR','1'),('irq_frame','VALID','1'),
                                ('irq_stats','CNT','1,2'),('irq_stats','MAX','EXCL')):
            bad={k:dict(v) for k,v in row.items()}; bad[key][field]=value
            with self.assertRaises(RuntimeError): acceptance.validate_sources(bad)

    def test_compute_console_rejects_motion_and_clearing(self):
        class Port:
            def write(self,_): raise AssertionError('Must not reach UART')
        for cmd in ('START','MOTOR TEST SPEED','CLEAR','BOOT A','FW CONFIRM'):
            with self.assertRaises(ValueError): acceptance.SourceConsole(Port()).query(cmd)

if __name__=='__main__': unittest.main()
