"""Binary replay, real C owner and compiled production safety invariants; no devices."""
import contextlib
import copy
import io
import json
from pathlib import Path
import re
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from test_torque_chain import FROZEN, function, GCC
from test_torque_chain_100ma import capture

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
import breakaway_current_report as report
import torque_chain_decode as torque


def trace(angles,sign=1,ma=100):
    data=capture(angles,sign)
    for i in range(len(angles)):
        row=list(torque.startup.FRAME.unpack_from(data,i*124))
        row[10]=row[12]=sign*ma/1000; row[11]=0
        row[34]=1; row[39]=row[40]=3
        torque.startup.FRAME.pack_into(data,i*124,*row)
    terminal=list(torque.startup.FRAME.unpack_from(data,32*124))
    terminal[0]=210000; terminal[10]=0; terminal[39]=terminal[40]=0
    torque.startup.FRAME.pack_into(data,32*124,*terminal)
    return data


def evidence(angles=None,sign=1,ma=100):
    if angles is None: angles=[sign*i*.25 for i in range(25)]
    t=torque.analyze_samples(trace(angles,sign,ma),sign,0,ma)
    snapshot=dict(first_fault=dict(valid=0),timing=dict(wall_max_us=30,deadline_miss=0,
                    actual_late_count=0,actual_margin_min_us=10))
    return t,snapshot


def evaluate(angles=None,sign=1,ma=100):
    t,s=evidence(angles,sign,ma)
    return report.evaluate(t,ma,sign,s,200)


class BreakawayTests(unittest.TestCase):
    def test_actual_c_owner_all_grades_directions_block_limit_and_races(self):
        out=ROOT/'tests/torque_chain_build'; out.mkdir(exist_ok=True)
        for opt in ('-O2','-Os'):
            exe=out/f'breakaway{opt}.exe'
            r=subprocess.run([GCC,'-std=c11',opt,'-Wall','-Wextra','-Werror',
                '-DFOC_BREAKAWAY_CURRENT_TEST=1','-I',str(ROOT/'firmware_common'),
                '-I',str(ROOT/'foc2_app_a/Core/Inc'),str(ROOT/'tests/torque_chain_host.c'),'-o',str(exe)],
                capture_output=True,text=True)
            self.assertEqual(r.returncode,0,r.stdout+r.stderr)
            r=subprocess.run([str(exe)],capture_output=True,text=True)
            self.assertEqual(r.returncode,0,r.stdout+r.stderr)

    def test_monotonic_both_signs_all_executable_currents(self):
        for sign in (-1,1):
            for ma in (100,120,150,180,200):
                r=evaluate(sign=sign,ma=ma)
                self.assertEqual(r['classification'],'CONTINUOUS_ROTATION',r['reasons'])
                self.assertEqual(r['motion_metrics']['path_to_net_ratio'],1)
                self.assertFalse(r['automatic_step']); self.assertFalse(r['mechanical_or_torque_certified'])
                self.assertEqual(r['Iq_command_A'],sign*ma/1000)

    def test_large_initial_displacement_then_plateau_is_not_continuous(self):
        angles=[i*2 for i in range(5)]+[8]*20
        r=evaluate(angles)
        self.assertEqual(r['classification'],'STICK_SLIP')
        self.assertFalse(r['criteria']['tail_keeps_moving'])
        self.assertFalse(r['criteria']['no_long_stationary'])
        self.assertEqual(r['motion_metrics']['path_to_net_ratio'],1)

    def test_oscillation_net_alone_does_not_pass_and_wrong_direction(self):
        angles=[i*.25+(1 if i%2 else 0) for i in range(25)]
        self.assertEqual(evaluate(angles)['classification'],'STICK_SLIP')
        self.assertEqual(evaluate([-i*.25 for i in range(25)])['classification'],'WRONG_DIRECTION')
        self.assertEqual(evaluate([0]*25)['classification'],'NO_MOTION')
        self.assertEqual(evaluate([i*.08 for i in range(25)])['classification'],'MARGINAL')

    def test_good_motion_bad_iq_does_not_pass(self):
        for key in ('Iq_A','voltage_saturated','current_path'):
            t,s=evidence()
            for row in t['rows']: row[key]=-.1 if key=='Iq_A' else 0 if key=='current_path' else 1
            r=report.evaluate(t,100,1,s,200)
            self.assertEqual(r['classification'],'MARGINAL')

    def test_fault_timing_and_actual_ref_mismatch(self):
        t,s=evidence()
        for key,value in (('deadline_miss',1),('actual_late_count',1),('wall_max_us',51),('actual_margin_min_us',0)):
            bad=copy.deepcopy(s); bad['timing'][key]=value
            self.assertEqual(report.evaluate(t,100,1,bad,200)['classification'],'TIMING_FAIL')
        bad=copy.deepcopy(s); bad['first_fault']['valid']=1
        self.assertEqual(report.evaluate(t,100,1,bad,200)['classification'],'FAULT')
        # Regression: requested 200mA but original setter clipped to 150mA.
        t,s=evidence(ma=200)
        for row in t['rows']: row['IqRef_A']=.15
        self.assertEqual(report.evaluate(t,200,1,s,200)['classification'],'REFERENCE_MISMATCH')

    def test_incomplete_gap_encoder_nonfinite_or_missing_off_is_not_pass(self):
        for mutation in ('short','gap','encoder','nan','terminal','late_terminal','late_window','nofaultfield','notiming'):
            t,s=evidence()
            if mutation=='short': t['rows']=t['rows'][:10]
            if mutation=='gap': t['rows'][10]['us']+=20000
            if mutation=='encoder': t['rows'][0]['encoder_valid']=0
            if mutation=='nan': t['rows'][0]['Iq_A']=float('nan')
            if mutation=='terminal': t['terminal']['gates']=3
            if mutation=='late_terminal': t['terminal']['us']=400000
            if mutation=='late_window':
                for row in t['rows']: row['us']+=50000
            if mutation=='nofaultfield': s['first_fault']={}
            if mutation=='notiming': s['timing']={}
            self.assertEqual(report.evaluate(t,100,1,s,200)['classification'],'INSUFFICIENT_DATA',mutation)

    def test_250_is_blocked_and_invalid_levels_not_accepted(self):
        self.assertEqual(evaluate(ma=250)['classification'],'LIMIT_BLOCKED')
        for ma in (99,110,201,251,400):
            with self.assertRaises(ValueError): evaluate(ma=ma)
        self.assertEqual(report.direct_limit_ma(),200)

    def test_empty_summary_is_unknown_not_zero(self):
        r=report.summarize([])
        self.assertIsNone(r['BREAKAWAY_IQ_POS']); self.assertIsNone(r['BREAKAWAY_IQ_NEG'])
        self.assertIsNone(r['IQ_FRICTION_FF'])
        self.assertEqual(sum(x['status']=='LIMIT_BLOCKED' for x in r['table']),2)
        self.assertFalse(r['automatic_control_write'])

    def test_summary_requires_unique_new_captures_and_lower_grades(self):
        r=evaluate(); r.update(evidence_kind='breakaway_capture',capture_identity_verified=True,capture_id='a')
        self.assertIsNone(report.summarize([r,r,r])['BREAKAWAY_IQ_POS'])
        batch=[]
        for ma in (100,120,150):
            for i in range(3):
                item=evaluate(ma=ma); item.update(evidence_kind='breakaway_capture',capture_identity_verified=True,capture_id=f'{ma}-{i}')
                if ma<150: item['classification']='STICK_SLIP'
                batch.append(item)
        self.assertEqual(report.summarize(batch)['BREAKAWAY_IQ_POS'],.15)
        self.assertIsNone(report.summarize(batch[3:])['BREAKAWAY_IQ_POS'])
        # Historical mode or unknown identity cannot establish a minimum.
        for item in batch: item['evidence_kind']='historical_torque_replay'
        self.assertIsNone(report.summarize(batch)['BREAKAWAY_IQ_POS'])

    def test_summary_asymmetric_directions_not_averaged_and_ff_does_not_exceed_limit(self):
        batch=[]
        for sign,minimum in ((1,100),(-1,180)):
            for ma in (100,120,150,180):
                if ma>minimum: continue
                for i in range(3):
                    item=evaluate(sign=sign,ma=ma)
                    item.update(evidence_kind='breakaway_capture',capture_identity_verified=True,capture_id=f'{sign}:{ma}:{i}')
                    if ma<minimum: item['classification']='STICK_SLIP'
                    batch.append(item)
        r=report.summarize(batch)
        self.assertEqual(r['BREAKAWAY_IQ_POS'],.1); self.assertEqual(r['BREAKAWAY_IQ_NEG'],.18)
        self.assertTrue(r['asymmetric']); self.assertEqual(r['ff_requested_A'],.207)
        self.assertTrue(r['ff_limit_blocked']); self.assertIsNone(r['IQ_FRICTION_FF'])
        self.assertAlmostEqual(r['ff_by_direction_A']['POS'],.115)

    def test_real_historical_replays_do_not_claim_new_measurements(self):
        paths=('torque100-run-1792331835484546300.json','torque100-negative-run-1792382127174402800.json',
               'torque200-limit-run-1792383430224485000.json')
        replay=[report.replay_receipt(ROOT/'tmp'/p) for p in paths]
        self.assertTrue(all(r['classification']=='STICK_SLIP' for r in replay))
        self.assertIsNone(report.summarize(replay)['BREAKAWAY_IQ_POS'])
        bad=report.replay_receipt(ROOT/'tmp/torque200-run-1792382815211725400.json')
        self.assertEqual(bad['classification'],'REFERENCE_MISMATCH')

    def test_frozen_math_safety_and_irq_objects(self):
        for slot in 'ab':
            text=[]
            for preset in ('TorqueChain200mADirectLimitDiagnostic','BreakawayCurrentDiagnostic'):
                base=ROOT/f'foc2_app_{slot}/build/{preset}'
                commands=json.loads((base/'compile_commands.json').read_text())
                command=next(x['command'] for x in commands if x['file'].endswith('/Core/Src/main.c'))
                text.append(subprocess.run(re.sub(r' -o \S+ -c ',' -E -P ',command),cwd=base,
                            capture_output=True,text=True,check=True).stdout)
            for name in FROZEN+('MotorControl_SetIq','FocFp_PushRawSafety','FocOcConfirm_Push','FocFeedbackSafety_Push','ProtectedLoop_GuardIrqBody'):
                self.assertEqual(function(text[0],name),function(text[1],name),name)
            for basename in ('stm32g4xx_it.c.obj','foc_adc_timing_stm32.c.obj'):
                data=[next((ROOT/f'foc2_app_{slot}/build/{p}').rglob(basename)).read_bytes() for p in
                      ('TorqueChain200mADirectLimitDiagnostic','BreakawayCurrentDiagnostic')]
                self.assertEqual(data[0],data[1])

    def test_default_off_and_cmake_rejects_missing_manual_protection_profile(self):
        for slot in 'ab':
            source=(ROOT/f'foc2_app_{slot}/CMakeLists.txt').read_text()
            self.assertRegex(source,r'option\(FOC_BREAKAWAY_CURRENT_TEST[^\n]+OFF\)')
            cm=source[source.index('if(FOC_BREAKAWAY_CURRENT_TEST AND NOT FOC_TORQUE_CHAIN_DIAG)'):]
            cm=cm[:cm.index('endif()')+7]
            with tempfile.TemporaryDirectory() as folder:
                guard=Path(folder)/'guard.cmake'; guard.write_text(cm)
                r=subprocess.run(['cmake','-DFOC_BREAKAWAY_CURRENT_TEST=ON','-DFOC_TORQUE_CHAIN_DIAG=OFF','-P',str(guard)],
                                 capture_output=True,text=True)
                self.assertNotEqual(r.returncode,0)
                self.assertIn('Breakaway test requires',r.stderr)
            cache=(ROOT/f'foc2_app_{slot}/build/BreakawayCurrentDiagnostic/CMakeCache.txt').read_text()
            self.assertIn('FOC_TORQUE_CHAIN_DIAG:BOOL=ON',cache)
            self.assertIn('FOC_BREAKAWAY_CURRENT_TEST:BOOL=ON',cache)
        with patch.object(sys,'argv',['report']),contextlib.redirect_stdout(io.StringIO()) as out:
            report.main()
        self.assertIsNone(json.loads(out.getvalue())['IQ_FRICTION_FF'])

    def test_matching_capture_identity_metadata_and_off_proof(self):
        elf=ROOT/'foc2_app_a/build/BreakawayCurrentDiagnostic/foc2.elf'
        table=report.symbols(elf); ram=bytearray(0x20000); flash=bytearray(0x80000)
        image=elf.with_suffix('.bin').read_bytes(); flash[0x8000:0x8000+len(image)]=image
        def put(name,data):
            address,size=table[name]; self.assertEqual(len(data),size)
            if 0x08000000<=address<0x08080000:
                self.assertEqual(flash[address-0x08000000:address-0x08000000+size],data)
                return
            offset=address-0x20000000; self.assertTrue(0<=offset<len(ram)); ram[offset:offset+size]=data
        put('breakaway_capture_tag',struct.pack('<I',0x42574159))
        put('breakaway_direct_limit_ma',struct.pack('<H',200))
        put('torque_diag',torque.META.pack(100,1,0,1,0,1,0,0,0,100))
        put('cl_startup',trace([i*.25 for i in range(25)]))
        timing=[0]*35; timing[2]=5100; put('foc_preempt_timing',struct.pack('<35I',*timing))
        probe=[0]*32; probe[0]=1; probe[5]=1700; put('foc_pwm_write_profile',struct.pack('<32I',*probe))
        with tempfile.TemporaryDirectory() as folder:
            rp=Path(folder)/'ram.bin'; fp=Path(folder)/'flash.bin'; rp.write_bytes(ram); fp.write_bytes(flash)
            r=report.capture_report(elf,rp,fp,0x08008000)
            self.assertEqual(r['classification'],'CONTINUOUS_ROTATION',r.get('reasons'))
            self.assertTrue(r['capture_identity_verified'])
            self.assertEqual(r['evidence_kind'],'breakaway_capture')
            saved=Path(folder)/'report.json'; r['classification']='NO_MOTION'
            saved.write_text(json.dumps(r))
            self.assertEqual(report.load_summary_report(saved)['classification'],'CONTINUOUS_ROTATION')
            with self.assertRaises(ValueError): report.capture_report(elf,rp,fp,0x08040000)
            flash[0x8000]^=1; fp.write_bytes(flash)
            with self.assertRaises(ValueError): report.capture_report(elf,rp,fp,0x08008000)


if __name__=='__main__': unittest.main()
