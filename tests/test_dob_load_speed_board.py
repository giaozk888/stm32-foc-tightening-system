
from app_source_view import read_app_source
import hashlib
import json
from pathlib import Path
import struct
import sys
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
import dob_load_speed_board as board
import dob_load_speed_decode as decode


class BoardTests(unittest.TestCase):
    def test_exact_candidate_and_unchanged_safety_profile(self):
        self.assertEqual(len(board.image()),228352)
        self.assertEqual(hashlib.sha256(board.IMAGE.read_bytes()).hexdigest(),board.SHA)

    def test_physical_gates_precede_any_hardware_setup(self):
        for args in (['--stage-off'],['--execute-powered','absent'],['--restore-b-drive-off','absent']):
            with patch.object(board,'configure') as configure:
                with self.assertRaises(SystemExit):board.main(args)
                configure.assert_not_called()

    def test_decode_first_and_latest2_and_validate_counters(self):
        ram=bytearray(0x20000)
        symbols={'dob_load_speed':(0x20001000,60),'mechanical_capture':(0x20002000,4712),
                 'dob_trend_continuous_arena':(0x20004000,4)}
        struct.pack_into('<12I2fI',ram,0x1000,1,0,0,100000,100000,5,2,1,100,50,4,100000,240.,120.,3)
        struct.pack_into('<I',ram,0x4000,0x20002000)
        tail=bytearray(200);struct.pack_into('<2I',tail,0,0xD1500001,5)
        for ordinal in (0,3,4):
            slot=0 if ordinal==0 else 1+(ordinal-1)%2
            struct.pack_into('<11I5f',tail,8+slot*64,1000*(ordinal+1),2,3,0,1,1,4,1,2,30000,0,240.,120.,.05,240.,0.)
        ram[0x2000+300:0x2000+400]=tail[:100];ram[0x2000+700:0x2000+800]=tail[100:]
        result=decode.decode(ram,symbols)
        self.assertEqual([e['event_ordinal'] for e in result['events']],[1,4,5])
        self.assertEqual(result['middle_events_overwritten'],2)
        self.assertEqual(result['telemetry']['selected_rpm'],120)
        struct.pack_into('<I',ram,0x1000+9*4,101)
        with self.assertRaises(ValueError):decode.decode(ram,symbols)

    def test_only_reviewed_main_hook_changed_from_simulated_owner(self):
        frozen=ROOT/'simulation/dob_simulink/load_speed_results/20261024_185249/frozen_sources/foc2_app_a/Core/Src/main.c'
        text=read_app_source(ROOT/'foc2_app_a/Core/Src/main.c')
        text=text.replace('#if defined(FOC_DOB_LOAD_SPEED)\n#include "dob_load_speed_candidate.h"\n#endif\n','')
        text=text.replace('#if defined(FOC_DOB_LOAD_SPEED)\n                speed_target_rpm=DobLoadSpeed_Select(sample.sample_us,(uint32_t)intent_fsm.state,\n                    speed_target_rpm,(float)intent_fsm.cfg.recipe.contact_rpm,\n                    speed_scurve.speed_rpm,speed_scurve.acceleration_rpm_s);\n#endif\n','')
        self.assertEqual(text,frozen.read_text())


if __name__=='__main__':unittest.main()
