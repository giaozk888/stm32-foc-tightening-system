import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import unittest
from test_torque_chain import GCC,FROZEN,function
from test_torque350_five_second import expanded
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
import ka_full_report as report

class FullTests(unittest.TestCase):
    def test_real_c_capture_wrap_flags_freeze_and_known_ka(self):
        out=ROOT/'tests/ka_full_build';out.mkdir(exist_ok=True)
        for opt in ('-Os','-O2'):
            exe=out/('full'+opt+'.exe')
            p=subprocess.run([GCC,'-std=c11',opt,'-Wall','-Wextra','-Werror',
                '-I',str(ROOT/'firmware_common'),str(ROOT/'tests/ka_full_host.c'),
                str(ROOT/'firmware_common/ka_full_diagnostic.c'),'-lm','-o',str(exe)],text=True,capture_output=True)
            self.assertEqual(p.returncode,0,p.stdout+p.stderr)
            p=subprocess.run([str(exe)],capture_output=True,text=True,check=True)
            captures=[report.decode_bytes(bytes.fromhex(x)) for x in p.stdout.splitlines()]
            self.assertEqual(len(captures),3)
            for c in captures[:2]:
                self.assertTrue(c['complete'] and c['reference_acceleration_covered'] and c['all_observations_valid'])
                self.assertEqual(c['span_us'],2400000)
                c['closure_verified']=True;c['board_acceptance_verified']=True;r=report.report(c)
                self.assertTrue(r['primary']['trusted'],r)
                self.assertAlmostEqual(r['candidate_ka'],.0001,delta=.00001)
                self.assertFalse(r['parameter_writes'])
            self.assertFalse(captures[2]['all_observations_valid'])
            self.assertGreater(captures[2]['meta']['read_failures'],0)

    def test_incomplete_and_negative_are_not_calibration(self):
        frames=[];speed=10
        for i in range(240):
            accel=100 if i%20<10 else 0;end=speed+accel*.01
            frames.append(dict(seq=i+1,speed_start_rpm=speed,speed_end_rpm=end,
                duration_s=.01,flags=0,matched_net_iq_mean_a=.1-.0001*accel));speed=end
        c=dict(frames=frames,complete=True,reference_acceleration_covered=True,
               closure_verified=True,board_acceptance_verified=True)
        self.assertIsNone(report.report(c)['candidate_ka'])
        c['complete']=False
        for f in frames:f['matched_net_iq_mean_a']=.2-f['matched_net_iq_mean_a']
        r=report.report(c);self.assertIsNone(r['candidate_ka']);self.assertFalse(r['next_ab_multipliers'])

    def test_control_unchanged_except_passive_observers(self):
        old=expanded('a','KaSynchronizedMemoryDiagnostic');new=expanded('a','KaFullAccelerationDiagnostic')
        for name in FROZEN+('Protocol_HandleLine','Protocol_PrintStatus','TighteningTask','Encoder_ElectricalAngleRad'):
            a=function(old,name);b=function(new,name)
            if name=='FOC_CurrentLoopStep':
                a=a.replace('ka_sync_diagnostic.publish_cycles_max','diag.publish_cycles_max')
                b=b.replace('ka_full_diagnostic.publish_cycles_max','diag.publish_cycles_max')
            if name=='FOC_EncoderSpeedUpdate':
                a=re.sub(r'KaSync_Observe\([^;]+;', '',a)
                b=re.sub(r'KaFull_Observe\([^;]+;', '',b)
            self.assertEqual(re.sub(r'\s+','',a),re.sub(r'\s+','',b),name)
        base=ROOT/'foc2_app_a/build/KaFullAccelerationDiagnostic'
        cmd=next(x['command'] for x in json.loads((base/'compile_commands.json').read_text()) if x['file'].endswith('/Core/Src/main.c'))
        self.assertIn('FOC_KA_FULL_DIAG=1',cmd);self.assertNotIn('FOC_KA_SYNC_DIAG=1',cmd)
        self.assertIn('SPEED_ACCEL_FF_KA_A_PER_RPM_S=0.0000000f',cmd)
        self.assertIn('PW_TARGET_UNIT_TESTS_DISABLED=1',cmd)
        self.assertLess((base/'foc2.bin').stat().st_size,229376)
        output=subprocess.run(['D:/software/arm/bin/arm-none-eabi-size.exe','-A',str(base/'foc2.elf')],capture_output=True,text=True,check=True).stdout
        sections=dict((a,int(b)) for a,b in re.findall(r'(?m)^(\.[\w.]+)\s+(\d+)\s+\d+',output))
        self.assertLess(sum(sections[n] for n in ('.data','.bss','._user_heap_stack')),131008)

if __name__=='__main__':unittest.main()
