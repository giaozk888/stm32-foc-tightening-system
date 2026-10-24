import json
import sys
from pathlib import Path
import unittest
from unittest.mock import patch,Mock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
import dq_audit_board as run


class BoardTests(unittest.TestCase):
    def test_default_files_only_exact_image_and_actual_B916(self):
        with patch.object(run.base.hw,'debug',side_effect=AssertionError('device')):
            self.assertEqual(run.main([]),0)
            self.assertEqual(len(run.image()),221100)
            self.assertEqual(run.base.old.zero.latest_meta(run.base.baseline())[2:6],(2,0,0,916))
            self.assertIs(run.base.TokenRecordedBoard,run.prior.ORIGINAL_BOARD)

    def test_no_physical_ack_no_devices(self):
        with patch.object(run.base.hw,'debug') as debug,patch.object(run.base.support.support,'open_port') as port:
            for args in (['--stage-off'],['--execute-powered','unused.json'],['--restore-b-drive-off','unused.json']):
                with self.assertRaises(SystemExit):run.main(args)
            debug.assert_not_called();port.assert_not_called()

    def test_wrong_audit_schema_blocks_original_start(self):
        good='1 OK DQA VERSION=1 SIGN_TEST=1 MODE=0 LD_NH=20030 LQ_NH=11180 LOG_US=100000 START_US=500000 STATIONARY_MRPM=1000'
        self.assertEqual(run.audit_status(good)['MODE'],'0')
        for wrong in (good.replace('MODE=0','MODE=1'),good.replace('VERSION=1','VERSION=2')):
            board=Mock();board.command.return_value=wrong
            with patch.object(run.prior,'ORIGINAL_MOTION') as motion:
                with self.assertRaises(RuntimeError):run.motion(board,dict(dq_enabled=False))
                motion.assert_not_called()

    def test_same_original_motion_and_fail_closed_DQ_switch(self):
        board=Mock();board.command.side_effect=[
            '1 OK DQA VERSION=1 SIGN_TEST=1 MODE=0 LD_NH=20030 LQ_NH=11180 LOG_US=100000 START_US=500000 STATIONARY_MRPM=1000',
            '2 OK DQ ON=0 LD_NH=20030 LQ_NH=11180',
            '3 OK DQ ON=0 LD_NH=20030 LQ_NH=11180']
        row=dict(dq_enabled=False)
        with patch.object(run.prior,'ORIGINAL_MOTION') as motion:
            run.motion(board,row);motion.assert_called_once_with(board,row)
        self.assertEqual(run.base.HOST_MAX_SECONDS,11.95)

    def test_root_receipt_tampering_blocks_before_any_hardware(self):
        actual=json.loads(run.ROOT_RECEIPT.read_text())
        wrong=dict(actual,metadata=actual['metadata'].copy());wrong['metadata'][8]+=1
        original=Path.read_text
        def read(path,*args,**kw):
            return json.dumps(wrong) if path.resolve()==run.ROOT_RECEIPT.resolve() else original(path,*args,**kw)
        with patch.object(Path,'read_text',read),patch.object(run.base.hw,'debug') as debug:
            with self.assertRaises(ValueError):run.configure(run.ROOT_RECEIPT)
            debug.assert_not_called()


if __name__=='__main__':unittest.main()
