"""SB3 command-level regressions and exact captured SB2 replay; no devices."""
import ctypes as C
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
from replay_voltage_x2_braking import trace
from test_voltage_x2 import function
GCC=r'D:\Qt\Tools\mingw1310_64\bin\gcc.exe'


class State(C.Structure):
    _fields_=[('previous',C.c_float),('direction',C.c_int8),('have_previous',C.c_uint8)]


class BrakeTrackTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.out=ROOT/'tests/speed_brake_track_build'; cls.out.mkdir(exist_ok=True); cls.libs=[]
        for opt in ('Os','O2'):
            path=cls.out/(opt+'.dll')
            subprocess.run([GCC,'-std=c11','-'+opt,'-Wall','-Wextra','-Werror','-pedantic',
                '-shared','-I',str(ROOT/'firmware_common'),
                str(ROOT/'tests/speed_brake_track_host.c'),'-o',str(path)],check=True)
            lib=C.CDLL(str(path))
            lib.brake_reset.argtypes=[C.POINTER(State)]
            lib.brake_apply.argtypes=[C.POINTER(State)]+[C.c_float]*3+[
                C.POINTER(C.c_float),C.c_float,C.POINTER(C.c_uint32)]
            lib.brake_step.argtypes=[C.POINTER(State),C.POINTER(C.c_float)]+[C.c_float]*4+[C.POINTER(C.c_uint32)]
            lib.bumpless_step.argtypes=[C.POINTER(C.c_float)]+[C.c_float]*3+[C.POINTER(C.c_uint32)]
            for name in ('brake_apply','brake_step','bumpless_step'): getattr(lib,name).restype=C.c_float
            cls.libs.append(lib)

    def apply(self,lib,state,integral,ref,filtered,instant,current):
        flag=C.c_uint32()
        out=lib.brake_apply(C.byref(state),ref,filtered,instant,C.byref(integral),current,C.byref(flag))
        return out,flag.value

    def test_single_raw_spike_cannot_trigger_fast_braking(self):
        for lib in self.libs:
            s=State(); i=C.c_float(.2)
            for raw in (0,100,0,0):
                out,flag=self.apply(lib,s,i,20,10,raw,.23)
                self.assertEqual(flag,0); self.assertAlmostEqual(out,.23,places=6)
                self.assertAlmostEqual(i.value,.2,places=6)

    def test_two_samples_revoke_driving_and_track_without_saved_integral(self):
        for lib in self.libs:
            for sign in (-1,1):
                s=State(); i=C.c_float(sign*.2)
                out,flag=self.apply(lib,s,i,sign*20,sign*10,sign*30,sign*.23)
                self.assertEqual(flag,0)
                out,flag=self.apply(lib,s,i,sign*20,sign*10,sign*40,sign*.23)
                self.assertEqual(flag,1); self.assertAlmostEqual(sign*out,-.03,places=6)
                self.assertAlmostEqual(sign*i.value,-.06,places=6)
                # Releasing limiter does not reload the earlier .2A integral.
                flags=C.c_uint32()
                recovered=lib.brake_step(C.byref(s),C.byref(i),sign*20,sign*19,sign*19,.001,C.byref(flags))
                self.assertLess(sign*recovered,0); self.assertLess(sign*i.value,0)

    def test_existing_filtered_overspeed_still_brakes_without_raw_history(self):
        for lib in self.libs:
            s=State(); i=C.c_float(.2)
            out,flag=self.apply(lib,s,i,20,30,0,.17)
            self.assertEqual(flag,1); self.assertAlmostEqual(out,-.03,places=6)

    def test_already_stronger_braking_is_not_weakened_and_current_is_bounded(self):
        for lib in self.libs:
            s=State(); i=C.c_float(-.2)
            out,flag=self.apply(lib,s,i,20,30,35,-.2)
            self.assertEqual(flag,0); self.assertAlmostEqual(out,-.2,places=6)
            for sign in (-1,1):
                s=State(); i=C.c_float(sign*.35)
                out,flag=self.apply(lib,s,i,sign*20,sign*500,sign*500,sign*.4)
                self.assertEqual(flag,1); self.assertAlmostEqual(sign*out,-.4,places=6)
                self.assertLessEqual(abs(i.value),.350001)

    def test_reset_zero_direction_change_and_bad_input_cannot_reuse_history(self):
        for lib in self.libs:
            for event in ('reset','zero','reverse','nonfinite'):
                s=State(); i=C.c_float(.2)
                self.apply(lib,s,i,20,10,80,.23)
                if event=='reset': lib.brake_reset(C.byref(s))
                elif event=='zero': self.apply(lib,s,i,0,0,80,.2)
                elif event=='nonfinite': self.apply(lib,s,i,20,10,float('nan'),.23)
                else:
                    out,flag=self.apply(lib,s,i,-20,-10,-80,-.23)
                    self.assertEqual(flag,0); continue
                out,flag=self.apply(lib,s,i,20,10,80,.23)
                self.assertEqual(flag,0)

    def test_stationary_load_retains_original_contact_reachability(self):
        for lib in self.libs:
            s=State(); i=C.c_float(); flags=C.c_uint32(); reached=False
            for tick in range(1400):
                out=lib.brake_step(C.byref(s),C.byref(i),min(20,(tick+1)*.2),0,0,.001,C.byref(flags))
                self.assertEqual(flags.value,0); self.assertLessEqual(abs(out),.400001)
                reached|=out>=.3
            self.assertTrue(reached)

    def test_actual_fault_inputs_reproduce_sb2_and_remove_positive_drive_earlier(self):
        rows=trace(); reports=[]
        for lib in self.libs:
            old=C.c_float(rows[0]['inferred_speed_I_A']); new=C.c_float(old.value)
            state=State(); flag=C.c_uint32()
            # First retained sample seeds history, not a fabricated prior speed.
            self.apply(lib,state,new,rows[0]['ref_rpm'],rows[0]['filtered_rpm'],rows[0]['instant_rpm'],rows[0]['iq_ref_A'])
            first=None; records=[]
            for a,b in zip(rows,rows[1:]):
                dt=((b['encoder_us']-a['encoder_us'])&0xffffffff)*1e-6
                sb2=lib.bumpless_step(C.byref(old),b['ref_rpm'],b['filtered_rpm'],dt,C.byref(flag))
                self.assertAlmostEqual(sb2,b['iq_ref_A'],places=5)
                sb3=lib.brake_step(C.byref(state),C.byref(new),b['ref_rpm'],b['filtered_rpm'],b['instant_rpm'],dt,C.byref(flag))
                records.append(dict(elapsed_us=b['elapsed_us'],filtered_rpm=b['filtered_rpm'],
                    instant_rpm=b['instant_rpm'],sb2_A=sb2,sb3_A=sb3,limited=flag.value,integral_A=new.value))
                if flag.value and first is None: first=records[-1]
                self.assertLessEqual(abs(sb3),.400001)
            self.assertIsNotNone(first)
            self.assertLess(first['filtered_rpm'],25)
            self.assertGreater(first['sb2_A'],0); self.assertLess(first['sb3_A'],0)
            reports.append(dict(first_brake=first,rows=records))
        (self.out/'captured-input-replay.json').write_text(json.dumps(dict(
            offline_only=True,predicts_motor_speed=False,
            limitation='Same recorded speed inputs, not a plant/stability simulation',results=reports),indent=2))

    def test_preprocessed_foc_protection_pipeline_fsm_frozen_and_no_new_warnings(self):
        names=('FOC_CurrentLoopStep','ProtectedLoop_PwmEntry','ProtectedLoop_PwmStage',
               'ProtectedLoop_AdcIrq','ProtectedLoop_Pair','FocCurrentValidation_Push',
               'FocFp_Poll','TighteningTask')
        for slot in 'ab':
            root=ROOT/f'foc2_app_{slot}/build'; sources={}; warnings={}; objects=[]
            for profile in ('VoltageX2Trial','SpeedBrakeTrackTrial'):
                base=root/profile; commands=json.loads((base/'compile_commands.json').read_text())
                cmd=next(x['command'] for x in commands if x['file'].endswith('/Core/Src/main.c'))
                sources[profile]=subprocess.run(re.sub(r' -o \S+ -c ',' -E -P ',cmd),
                    cwd=base,capture_output=True,text=True,check=True).stdout
                check=subprocess.run(re.sub(r' -o \S+ -c ',' -fsyntax-only ',cmd),
                    cwd=base,capture_output=True,text=True,check=True)
                warnings[profile]=set(re.findall(r'warning: (.*)',check.stderr))
                objects.append(next(base.rglob('foc_adc_timing_stm32.c.obj')).read_bytes())
            for name in names:
                self.assertEqual(function(sources['VoltageX2Trial'],name),function(sources['SpeedBrakeTrackTrial'],name),name)
            self.assertEqual(objects[0],objects[1])
            self.assertFalse(warnings['SpeedBrakeTrackTrial']-warnings['VoltageX2Trial'])
            text=sources['SpeedBrakeTrackTrial']
            self.assertIn('SpeedBrakeTrack_Reset(&speed_brake_track)',function(text,'FOC_ResetController'))
            outer=function(text,'FOC_EncoderSpeedUpdate')
            self.assertIn('if (mode != MOTOR_MODE_SPEED) SpeedBrakeTrack_Reset',outer)
            call=outer.index('SpeedBrakeTrackResult brake=')
            self.assertIn('if (mode == MOTOR_MODE_SPEED)',outer[call-80:call])
            self.assertGreater(call,outer.index('speed_integrator_A = i_candidate'))
            self.assertGreater(outer.index('foc_iq_ref_A = iq_cmd'),call)
            block=outer[outer.index('if (run_speed_pi != 0U)'):]
            self.assertEqual(block.count('foc_iq_ref_A = iq_cmd'),1)
            self.assertIn('iq_cmd=brake.current_A',block)

    def test_images_are_separate_and_historical_identity_preserved(self):
        oldsha={'a':'6f83652e152f569d3830ca2b5d1b9033c475140967b1db34f5bdc5ebed969098',
                'b':'c00911eeed628ef677eef4eb7c3b97884aef4cd52f6f5e98a3f2b0c47ffad663'}
        for slot in 'ab':
            root=ROOT/f'foc2_app_{slot}/build'
            self.assertEqual(hashlib.sha256((root/'VoltageX2Trial/foc2.bin').read_bytes()).hexdigest(),oldsha[slot])
            data=(root/'SpeedBrakeTrackTrial/foc2.bin').read_bytes()
            self.assertLessEqual(len(data),229376); self.assertIn(b'SPEED_CTRL=SB3',data)
            self.assertNotIn(b'SPEED_CTRL=SB2',data)
            for marker in (b'VLIMIT_MV=1600 ILIMIT_MV=750',b'METHOD=TWO_SAMPLE',b'TRIP_MA=4000'):
                self.assertIn(marker,data)

    def test_incomplete_profile_cannot_enable_sb3(self):
        required=['FOC_SPEED_BUMPLESS','FOC_VOLTAGE_X2_TRIAL','FOC_PWM_PIPELINE_CLOSED_LOOP']
        for missing in required:
            flags=['-DFOC_SPEED_BRAKE_TRACK=1']+['-D'+x+'=1' for x in required if x!=missing]
            result=subprocess.run([GCC,'-std=c11','-fsyntax-only','-x','c',
                '-I',str(ROOT/'firmware_common'),*flags,'-'],
                input='#include "speed_brake_track.h"\n',capture_output=True,text=True)
            self.assertNotEqual(result.returncode,0)
            self.assertIn('SB3 requires',result.stderr)


if __name__=='__main__': unittest.main()
