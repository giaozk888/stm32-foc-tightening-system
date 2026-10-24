import sys
import unittest
from pathlib import Path
from unittest.mock import patch,Mock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
import dq_decoupling_fsm_board as run


class DqBoardTests(unittest.TestCase):
    def test_default_files_only_and_pinned_b908(self):
        with patch.dict(run.base.__dict__,{}),patch.object(run.base.hw,'debug',side_effect=AssertionError('device')):
            self.assertEqual(run.main([]),0)
            self.assertEqual(len(run.image()),219300)
            self.assertEqual(run.base.old.zero.latest_meta(run.base.baseline())[2:6],(2,0,0,908))

    def test_missing_physical_conditions_never_touch_devices(self):
        with patch.object(run.base.hw,'debug') as debug,patch.object(run.base.support.support,'open_port') as port:
            for args in (['--stage-off'],['--execute-powered','unused.json'],['--restore-b-drive-off','unused.json']):
                with self.assertRaises(SystemExit):run.main(args)
            debug.assert_not_called();port.assert_not_called()

    def test_wrong_switch_or_inductance_blocks_start(self):
        good='OK DQ ON=0 LD_NH=20030 LQ_NH=11180 VALID=0'
        self.assertEqual(run.dq_status(good,False)['ON'],'0')
        for bad in (good.replace('ON=0','ON=1'),good.replace('11180','11000'),
                    'OK DQ ON=0 LD_UH= LQ_UH='):
            with self.assertRaises(RuntimeError):run.dq_status(bad,False)
        board=Mock();board.command.return_value=good.replace('ON=0','ON=1')
        with patch.object(run,'ORIGINAL_MOTION') as motion:
            with self.assertRaises(RuntimeError):run.motion(board,dict(dq_enabled=False))
            motion.assert_not_called()

    def test_single_original_start_owner_and_no_changes_to_limits(self):
        board=Mock();board.command.return_value='OK DQ ON=1 LD_NH=20030 LQ_NH=11180'
        row=dict(dq_enabled=True)
        with patch.object(run,'ORIGINAL_MOTION') as original:
            run.motion(board,row)
            original.assert_called_once_with(board,row)
        self.assertEqual(board.command.call_args_list[0].args[0],'MOTOR TEST DQ ON')
        self.assertEqual(run.base.HOST_MAX_SECONDS,11.95)


if __name__=='__main__':unittest.main()
