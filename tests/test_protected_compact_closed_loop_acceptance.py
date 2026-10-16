"""No board I/O: exact short-trial console gates and pre-motion rejection."""
import copy
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
import protected_compact_closed_loop_acceptance as trial

def good():
    return dict(state=dict(SD='0',MOE='0',CCER='0',FLAGS='0',FAULT='0',QUALIFIED='0',
            STATE='1',USED='0',QUEUED='0',ARMED='1',ZERO='3'),
        timing=dict(CLOCK_HZ='1000000',LATE='0',MAX_US='44',WORK='2000',OUTER='200',IRQ='4000',
            LEASE_US='400000',SAMPLE_US='100',OUTER_US='2000'),
        protection=dict(FILTER='TREND4',OC='2_OF_3',TRIP_MA='4000',STATE='0',REASON='0',
            FLAGS='0',BUDGET='6',STREAK='4'),
        adc=dict(DWT='1',MISS='0',PF='0',MAX_CYC='7521',PAIRS='4000'),
        encoder_dma=dict(FAIL='0',TIMEOUT='0',IO='0',SCHED='0',STALE='0',READS='200'),
        encoder_snapshot=dict(VALID='0'),encoder_irq=dict(VALID='0',MAX_LATE_US='13'),
        cost=dict(TRIG='POLY9_8',DWT='1',CPU_MAX_CYC='3000',PREEMPT_MAX_CYC='3000',
            PAIR_MAX_US='30',MATH_MAX_US='20'),
        late_frame=dict(PATH='PAIR2',VALID='0',SEQ='0',US='0',PAIR_US='0',MATH_US='0',WALL_CYC='0',IRQ_CYC='0'),
        profile=dict(NAME='COMPACT_CLOSED_LOOP',HARD_OFF='0',ADAPT='0',ZERO='BOUNDED',
            LOCAL='1',RPM='20',LEASE_US='400000',QUALIFIED='0'),
        ram=dict(ENABLED='1',HARD_OFF='0',DEADLINE_US='50'),
        compact=dict(ENABLED='1',HARD_OFF='0',FIXED_OPS='1',GUARD_US='25',DEADLINE_US='50'),
        zero=dict(STATE='3',REASON='0',N='4000'),
        buffer=dict(STK_VALID='1',FREE_B='1000',DONE='10'),fault=dict(VALID='0'),status='OK FLT=0')

class CompactMotorAcceptanceTests(unittest.TestCase):
    def test_all_runtime_gates_required_before_motion(self):
        trial.validate(good(),ready=True)
        for group,key,value in [('zero','STATE','4'),('encoder_dma','FAIL','1'),
            ('adc','MAX_CYC','8500'),('adc','MISS','1'),('timing','MAX_US','50'),
            ('timing','LATE','1'),('protection','TRIP_MA','8000'),('fault','VALID','1'),
            ('state','SD','1'),('profile','ADAPT','1'),('ram','HARD_OFF','1'),
            ('compact','GUARD_US','50'),('buffer','FREE_B','0')]:
            row=good(); row[group][key]=value
            with self.subTest(group=group,key=key):
                with self.assertRaises(RuntimeError): trial.validate(row,ready=True)

    def test_console_single_commit_single_motion_and_no_general_commands(self):
        class Port:
            def __init__(self): self.sent=[]
            def write(self,data): self.sent.append(data)
        port=Port(); uart=trial.MotorConsole(port)
        uart.read_line=lambda timeout: f'{uart.request} OK TEST'
        for command in ('START','RESET','FW BEGIN','BOOT A','FAULT CLEAR','MOTOR TEST SPEED 100'):
            with self.assertRaises(ValueError): uart.query(command)
        self.assertEqual(port.sent,[])
        uart.query('FW END'); uart.query('MOTOR TEST SPEED')
        for command in ('FW END','MOTOR TEST SPEED'):
            with self.assertRaises(ValueError): uart.query(command)
        self.assertEqual(len(port.sent),2)
        self.assertEqual((uart.ends,uart.starts),(1,1))

    def test_missing_user_state_or_wrong_receipt_refused_before_probe(self):
        for flags in ([],['--allow-trial-and-single-short-speed']):
            with patch.object(sys,'argv',['trial','--stage',str(trial.STAGE),*flags]), \
                 patch.object(trial.profile,'Board') as board:
                with self.assertRaises(SystemExit): trial.main()
                board.assert_not_called()
        with self.assertRaises(RuntimeError): trial.stage_evidence(ROOT/'other-stage.json')

if __name__=='__main__': unittest.main()
