"""SB2 exact C kernel and recorded-input counterfactuals, never a motor model."""

from app_source_view import read_app_source
import ctypes as C
import hashlib
import json
from pathlib import Path
import re
import subprocess
import unittest

ROOT=Path(__file__).resolve().parents[1]
GCC=r'D:\Qt\Tools\mingw1310_64\bin\gcc.exe'


class SpeedBumplessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.out=ROOT/'tests/speed_bumpless_build'; cls.out.mkdir(exist_ok=True)
        cls.libs=[]
        for opt in ('Os','O2'):
            dll=cls.out/(opt+'.dll')
            subprocess.run([GCC,'-std=c11','-'+opt,'-Wall','-Wextra','-Werror','-pedantic',
                '-shared','-I',str(ROOT/'firmware_common'),
                str(ROOT/'tests/speed_bumpless_host.c'),'-o',str(dll)],check=True)
            lib=C.CDLL(str(dll))
            lib.bumpless_apply.argtypes=[C.c_float]*5+[C.POINTER(C.c_uint32)]
            lib.bumpless_apply.restype=C.c_float
            lib.bumpless_step.argtypes=[C.POINTER(C.c_float)]+[C.c_float]*3+[C.POINTER(C.c_uint32)]
            lib.bumpless_step.restype=C.c_float
            lib.speed_test_step.argtypes=[C.POINTER(C.c_float)]+[C.c_float]*3+[C.c_uint,C.POINTER(C.c_uint32)]
            lib.speed_test_step.restype=C.c_float
            cls.libs.append(lib)

    def test_real_operating_point_unloads_at_most_10mA_not_full_reset(self):
        for lib in self.libs:
            for sign in (-1,1):
                flags=C.c_uint32(); integral=C.c_float(sign*.2391)
                lib.bumpless_step(C.byref(integral),sign*20,sign*31.03976,.001,C.byref(flags))
                self.assertAlmostEqual(integral.value,sign*.2291,places=6)
                self.assertEqual(flags.value,4)
                # No legacy5mA + SB2's10mA double subtraction.
                self.assertGreater(abs(integral.value),.225)

    def test_recovery_reuses_remaining_integral_and_never_exceeds_original_candidate(self):
        for lib in self.libs:
            flags=C.c_uint32()
            value=lib.bumpless_apply(.2291,.22946,20,2,.001,C.byref(flags))
            self.assertAlmostEqual(value,.22946,places=6)
            self.assertEqual(flags.value,0)
            value=lib.bumpless_apply(.1,.1008,20,-20,.001,C.byref(flags))
            self.assertAlmostEqual(value,.1004,places=6)
            self.assertEqual(flags.value,1)

    def test_braking_integral_and_ordinary_unwinding_are_not_erased(self):
        for lib in self.libs:
            for sign in (-1,1):
                flags=C.c_uint32()
                value=lib.bumpless_apply(sign*.2,sign*.1996,sign*20,sign*21,.001,C.byref(flags))
                self.assertAlmostEqual(value,sign*.1996,places=6)
                value=lib.bumpless_apply(-sign*.1,-sign*.10022,sign*20,sign*31,.001,C.byref(flags))
                self.assertAlmostEqual(value,-sign*.10022,places=6)
                self.assertEqual(flags.value,0)

    def test_boundary_and_dt_scaling_are_symmetric(self):
        for lib in self.libs:
            for dt in (.0005,.001,.0015):
                for sign in (-1,1):
                    flags=C.c_uint32()
                    value=lib.bumpless_apply(sign*.2,sign*.195,sign*20,sign*25,dt,C.byref(flags))
                    self.assertAlmostEqual(value,sign*(.2-10*dt),places=6)
                    self.assertEqual(flags.value,4)
            flags=C.c_uint32()
            lib.bumpless_apply(.2,.1999,20,24.99,.001,C.byref(flags))
            self.assertEqual(flags.value,0)

    def test_persistent_overspeed_removes_driving_integral_and_cannot_reload_it(self):
        for lib in self.libs:
            for sign in (-1,1):
                flags=C.c_uint32(); integral=C.c_float(sign*.24)
                for _ in range(60):
                    previous=integral.value
                    iq=lib.bumpless_step(C.byref(integral),sign*20,sign*31,.001,C.byref(flags))
                    self.assertLessEqual(abs(integral.value-previous),.010001)
                self.assertLess(sign*iq,0)
                self.assertLessEqual(sign*integral.value,0)

    def test_short_peak_retains_integral_instead_of_dumping_all(self):
        for lib in self.libs:
            flags=C.c_uint32(); integral=C.c_float(.2391)
            # Constructed1kHz scenario using measured peak, NOT the missing real peak waveform.
            for speed in [26,29,31.03976,29,26,24,22,20,18]:
                lib.bumpless_step(C.byref(integral),20,speed,.001,C.byref(flags))
            self.assertGreater(integral.value,.18)

    def test_stall_contact_reachability_without_output_limit_change(self):
        for lib in self.libs:
            for sign in (-1,1):
                integral=C.c_float(); flags=C.c_uint32(); hit=None
                for tick in range(1600):
                    ref=sign*min(20,(tick+1)*.2)
                    iq=lib.bumpless_step(C.byref(integral),ref,0,.001,C.byref(flags))
                    self.assertLessEqual(abs(iq),.400001)
                    self.assertLessEqual(abs(integral.value),.350001)
                    if sign*iq>=.3 and hit is None: hit=tick+1
                self.assertIsNotNone(hit); self.assertLess(hit,900)

    def test_real_old_overspeed_input_unloads_faster_than_legacy_but_is_not_motor_simulation(self):
        rows=json.loads((ROOT/'tmp/loaded-fsm-motion-1792300223073650000-overspeed-analysis.json').read_text())['rows']
        for lib in self.libs:
            old=C.c_float(rows[0]['speed_integral_inferred_A']); new=C.c_float(old.value)
            flags=C.c_uint32()
            for row in rows[1:]:
                dt=row['dt_us']*1e-6
                legacy=lib.speed_test_step(C.byref(old),row['ref_rpm'],row['filtered_rpm'],dt,0,C.byref(flags))
                self.assertAlmostEqual(legacy,row['iq_ref_A'],places=5)
                previous=new.value
                output=lib.bumpless_step(C.byref(new),row['ref_rpm'],row['filtered_rpm'],dt,C.byref(flags))
                self.assertLessEqual(abs(new.value-previous),10*dt+1e-6)
            self.assertGreater(legacy,0); self.assertLess(output,0)

    def test_saturation_and_zeroed_mode_entry_cannot_resurrect_saved_torque(self):
        for lib in self.libs:
            flags=C.c_uint32()
            for sign in (-1,1):
                integral=C.c_float(sign*.35)
                iq=lib.bumpless_step(C.byref(integral),sign*120,0,.001,C.byref(flags))
                self.assertLessEqual(abs(iq),.400001)
                self.assertLessEqual(abs(integral.value),.350001)
                integral.value=0 # Existing mode reset: helper has no state to restore.
                iq=lib.bumpless_step(C.byref(integral),0,0,.001,C.byref(flags))
                self.assertEqual(iq,0); self.assertEqual(integral.value,0)

    def test_production_calls_capture_prebleed_after_mode_reset_and_keep_clamps(self):
        for slot in 'ab':
            text=read_app_source(ROOT/f'foc2_app_{slot}/Core/Src/main.c')
            begin=text.index('if (mode != previous_mode)')
            capture=text.index('float sb2_previous_A=')
            apply=text.index('SpeedStartupBrakeResult guarded=SpeedBumpless_Apply')
            self.assertLess(begin,capture); self.assertLess(capture,apply)
            self.assertIn('sb2_previous_A,i_candidate,speed_ref_rpm,encoder_speed_rpm',text[apply:apply+300])
            self.assertIn('if (mode == MOTOR_MODE_SPEED)',text[apply-130:apply])
            tail=text[apply:apply+1900]
            self.assertIn('SPEED_INT_LIMIT_A',tail); self.assertIn('speed_iq_limit_A',tail)

    def test_both_candidate_builds_and_historical_images_separate(self):
        for slot in 'ab':
            p=ROOT/f'foc2_app_{slot}/build/SpeedBumplessTrial'
            data=(p/'foc2.bin').read_bytes()
            self.assertLessEqual(len(data),224*1024)
            self.assertIn(b'SPEED_CTRL=SB2',data); self.assertNotIn(b'SPEED_CTRL=SB1',data)
            self.assertIn(b'METHOD=TWO_SAMPLE',data); self.assertIn(b'TRIP_MA=4000',data)
            self.assertIn(b'ZERO CAL valid=',data)
        data=(ROOT/'foc2_app_a/build/ZeroValidAdmissionTrial/foc2.bin').read_bytes()
        self.assertEqual(hashlib.sha256(data).hexdigest(),
            '11b99efb2323f552b568bb3e8dcbf2f1e0cab5257bd81f15816be2fad475e7e6')

    def test_no_new_source_warnings_against_sb1(self):
        for slot in 'ab':
            root=ROOT/f'foc2_app_{slot}/build'; warnings={}
            for profile in ('ZeroValidAdmissionTrial','SpeedBumplessTrial'):
                commands=json.loads((root/profile/'compile_commands.json').read_text())
                cmd=next(x['command'] for x in commands if x['file'].endswith('/Core/Src/main.c'))
                p=subprocess.run(re.sub(r' -o \S+ -c ',' -fsyntax-only ',cmd),
                    cwd=root/profile,capture_output=True,text=True)
                self.assertEqual(p.returncode,0,p.stderr)
                warnings[profile]=set(re.findall(r'warning: (.*)',p.stderr))
            self.assertFalse(warnings['SpeedBumplessTrial']-warnings['ZeroValidAdmissionTrial'],warnings)

    def test_preprocessed_current_math_protection_pipeline_and_fsm_identical(self):
        def function(text,name):
            match=re.search(r'\b'+name+r'\s*\([^;{}]*\)\s*\{',text)
            self.assertIsNotNone(match,name)
            start=match.start(); point=match.end(); depth=1
            while depth:
                if text[point]=='{': depth+=1
                elif text[point]=='}': depth-=1
                point+=1
            return text[start:point]
        for slot in 'ab':
            root=ROOT/f'foc2_app_{slot}/build'; sources={}
            for profile in ('ZeroValidAdmissionTrial','SpeedBumplessTrial'):
                commands=json.loads((root/profile/'compile_commands.json').read_text())
                cmd=next(x['command'] for x in commands if x['file'].endswith('/Core/Src/main.c'))
                p=subprocess.run(re.sub(r' -o \S+ -c ',' -E -P ',cmd),
                    cwd=root/profile,capture_output=True,text=True,check=True)
                sources[profile]=p.stdout
            for name in ('FOC_CurrentLoopStep','ProtectedLoop_PwmEntry','ProtectedLoop_Pair',
                         'ProtectedLoop_SetDuty','ProtectedLoop_AdcIrq',
                         'FocCurrentValidation_Push','TighteningTask'):
                self.assertEqual(function(sources['ZeroValidAdmissionTrial'],name),
                                 function(sources['SpeedBumplessTrial'],name),name)


if __name__=='__main__': unittest.main()
