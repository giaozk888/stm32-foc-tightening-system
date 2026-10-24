"""105mA host adapter: files and mocked gates only, no target access."""
import json
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
import friction105_fsm_board as selected


class Friction105BoardTests(unittest.TestCase):
    def test_pinned_image_b796_baseline_and_files_only_default(self):
        base=selected.base
        self.assertEqual(len(selected.image()),217420)
        with patch.dict(base.__dict__,{}):
            selected.install();selected.configure(selected.RESTORE)
            self.assertEqual(base.old.zero.latest_meta(base.baseline())[2:6],(2,0,0,796))
            self.assertEqual(base.FRICTION_A,.105)
            self.assertEqual(base.BASE_RESTORE_RECEIPT,selected.RESTORE.resolve())
            with self.assertRaisesRegex(ValueError,'historical root'):
                selected.configure(base.ROOT_RESTORE)
        p=subprocess.run([sys.executable,str(ROOT/'tools/friction105_fsm_board.py')],
            capture_output=True,text=True,timeout=10)
        self.assertEqual(p.returncode,0,p.stdout+p.stderr)
        self.assertIn('no devices',p.stdout)

    def test_old_200ma_status_and_wrong_switch_block_start(self):
        with patch.object(selected.base,'FRICTION_A',.105):
            text='OK FRC ON=0 I_UA=105000 DB_MRPM=2000 FF_ON=1 KA_NA_PER_RPM_S=187500 TOKENIZED=1'
            self.assertEqual(selected.base.friction_status(text,False)['I_UA'],'105000')
            for wrong in (text.replace('105000','200000'),text.replace('ON=0','ON=1'),
                          text.replace('DB_MRPM=2000','DB_MRPM=0')):
                with self.assertRaisesRegex(RuntimeError,'no START'):
                    selected.base.friction_status(wrong,False)

    def test_missing_physical_state_never_opens_device(self):
        b=selected.base
        with patch.object(b.hw,'debug') as debug,patch.object(b.support.support,'open_port') as port:
            for f,args in ((b.stage,({},'unused',b'')),
                (b.execute,({},'unused',ROOT/'tmp/unused.json',b'')),
                (b.restore,({},'unused',ROOT/'tmp/unused.json',b''))):
                with self.assertRaises(ValueError):f(*args)
            debug.assert_not_called();port.assert_not_called()


if __name__=='__main__':unittest.main()
