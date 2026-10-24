import json
import math
from pathlib import Path
import struct
import subprocess
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
import current_pi_compare as compiler
import mechanical_identification_report as report


def simulated():
    captures=[]
    for repeat in range(3):
        for sign in (-1,1):
            session=f'session-{repeat}-{sign}';rows=[];dt=.064
            def w(t):return sign*(16+7*math.sin(2*t)+3*math.cos(5*t))
            for i in range(80):
                t=repeat*.19+i*dt;end=t+dt
                wm=sign*(16+7*(math.cos(2*t)-math.cos(2*end))/(2*dt)+3*(math.sin(5*end)-math.sin(5*t))/(5*dt))
                alpha=(w(end)-w(t))/dt
                iq=.004*alpha+.002*wm+.08*sign+.01
                rows.append(dict(session=session,index=i+1,start_us=i*64000,end_us=(i+1)*64000,
                    dt_s=dt,omega_start_rad_s=w(t),omega_end_rad_s=w(end),omega_mean_rad_s=wm,
                    iq_mean_a=iq,iq_matched_mean_a=iq,id_abs_mean_a=.005,flags=0,samples=64))
            captures.append(dict(rows=rows,board_verified=True))
    return captures


class MechanicalTests(unittest.TestCase):
    def test_normalized_recovery_and_64_128ms_consistency(self):
        r=report.report(simulated())
        self.assertTrue(r['normalized_qualified'],r['problems'])
        self.assertTrue(r['dob_shadow_ready'])
        for key,val in (('j_over_kt',.004),('b_over_kt',.002),('coulomb_over_kt',.08),('bias_a',.01)):
            self.assertAlmostEqual(r['primary'][key],val,places=10)
            self.assertAlmostEqual(r['sensitivity'][key],val,places=10)
        self.assertGreater(r['primary']['r2'],.99999)
        self.assertIsNone(r['absolute_parameters'])
        self.assertFalse(r['kt_independently_identified'])
        self.assertFalse(r['parameter_writes']);self.assertFalse(r['dob_control_enabled'])
        json.dumps(r,allow_nan=False)

    def test_absolute_parameters_require_separate_calibrated_dq_kt(self):
        c=simulated()
        self.assertIsNone(report.report(c,.02)['absolute_parameters'])
        a=report.report(c,.02,True,'external torque reference: Nm/dq-A')['absolute_parameters']
        b=report.report(c,.04,True,'different calibrated motor scale')['absolute_parameters']
        self.assertAlmostEqual(a['J_kg_m2'],.00008)
        self.assertAlmostEqual(a['B_nm_s_per_rad'],.00004)
        self.assertAlmostEqual(b['J_kg_m2'],a['J_kg_m2']*2)
        with self.assertRaises(ValueError):report.report(c,.02,True,'')
        for bad in (0,-1,float('nan')):
            with self.assertRaises(ValueError):report.report(c,bad)

    def test_single_direction_and_constant_speed_cannot_claim_mechanics(self):
        c=[s for s in simulated() if s['rows'][0]['omega_start_rad_s']>0]
        r=report.report(c)
        self.assertFalse(r['normalized_qualified'])
        self.assertIn('BOTH_DIRECTIONS_REQUIRED',r['primary']['problems'])
        for session in c:
            for row in session['rows']:
                row.update(omega_start_rad_s=20.,omega_end_rad_s=20.,omega_mean_rad_s=20.)
        r=report.report(c)
        self.assertIn('INSUFFICIENT_ACCELERATION_EXCITATION',r['primary']['problems'])
        self.assertFalse(r['normalized_qualified'])

    def test_quality_flags_admission_no_residual_cherry_picking(self):
        c=simulated();bad=c[0]['rows'][12];bad['flags']=4
        rows=[r for s in c for r in s['rows']]
        good,reject=report.windows(rows,1)
        self.assertEqual(len(good),len(rows)-3) # fixed next-two-bin washout
        self.assertIn('QUALITY_FLAGS',reject[0]['reasons'])
        self.assertTrue(all('POST_INVALID_FILTER_SETTLING' in r['reasons'] for r in reject[1:]))
        # Unflagged huge residuals stay in the fit and make it fail quality.
        for i,row in enumerate(c[1]['rows']):row['iq_matched_mean_a']+=.5 if i%2 else -.5
        r=report.report(c)
        self.assertFalse(r['normalized_qualified'])
        self.assertIn('POOR_MODEL_FIT',r['primary']['problems'])
        self.assertEqual(r['primary']['n'],len(rows)-3)

    def test_fault_or_missing_provenance_never_qualifies_shadow(self):
        c=simulated();c[0]['board_verified']=False
        r=report.report(c,.02,True,'reference')
        self.assertFalse(r['dob_shadow_ready']);self.assertIsNone(r['absolute_parameters'])
        self.assertIn('BOARD_ACCEPTANCE_NOT_VERIFIED',r['problems'])

    def test_receipt_guard_requires_registers_and_independent_fault_evidence(self):
        r=dict(preflight_pass=True,final_outputs_off=True,final_cpu_halted=True,
            all_app_private_unchanged=True,start_attempts=1,
            outputs=dict(VTOR=0x08008000,SD=0,BDTR=0,CCER=0),
            snapshot=dict(timing=dict(deadline_miss=0,actual_late_count=0,wall_max_us=33,actual_margin_min_us=12),
                cur_confirm=dict(fault=0),first_fault=dict(valid=0)),
            terminal_status=dict(FLT='0',OUTCOME='RUNDOWN_TIMEOUT'),
            postflight={'MOTOR TEST FAULT':'OK VALID=0 FLAGS=0'},
            encoder_saved=dict(first_fault=dict(valid=0),counters=dict(timeouts=0,dma_errors=0,schedule_misses=0,control_stale=0)))
        self.assertTrue(report.board_acceptance(r))
        r['snapshot']['first_fault']=dict(valid=1,domain=3,fault_reason=3,timeout_reason=0,protection_flags=0)
        self.assertTrue(report.board_acceptance(r))
        r['snapshot']['first_fault']['protection_flags']=1
        self.assertFalse(report.board_acceptance(r))
        r['snapshot']['first_fault']=dict(valid=0);r['outputs']['BDTR']=0x8000
        self.assertFalse(report.board_acceptance(r))

    def test_decode_wrap_timestamp_and_abi(self):
        raw=bytearray(report.SIZE);start=0xffff8000;end=(start+64000)&0xffffffff
        struct.pack_into('<IIHHhH5f',raw,0,end,120,64000,64,100,0,20.,19.,.1,.09,.005)
        values=[1,1,65,0,start,end,100,120,0,50,18.,1,end,end,120,0,0,0,0.,.1,.1,0.,0.,0.,0.,20.]
        struct.pack_into('<10If6Ii8f',raw,4608,*values)
        c=report.decode_bytes(raw)
        self.assertEqual(len(c['rows']),1);self.assertAlmostEqual(c['span_s'],.064)
        self.assertAlmostEqual(c['rows'][0]['omega_start_rad_s'],18.)
        raw[0:4]=struct.pack('<I',(end+1)&0xffffffff)
        with self.assertRaises(ValueError):report.decode_bytes(raw)

    def test_native_capture_publication_freeze_reset_and_dob_shadow(self):
        code=r'''
#include <assert.h>
#include <math.h>
#include <string.h>
#include "mechanical_identification.h"
#include "mechanical_dob_shadow.h"
static MechanicalCapture capture;
int main(void){
MechanicalCurrent c={0},copy;volatile MechanicalCurrent publisher={0};
assert(!Mechanical_TryRead(&publisher,&copy));
Mechanical_Publish(&publisher,20,100,120,.005f,.1f,0);
assert(Mechanical_TryRead(&publisher,&copy) && copy.seq==20 && copy.iq==.1f);
publisher.version=1;assert(!Mechanical_TryRead(&publisher,&copy));
Mechanical_Reset(&capture);
for(unsigned i=0;i<8200;i++){
 uint32_t t=0xffff0000U+i*1000U;c=(MechanicalCurrent){2,i*20U+20U,t-20U,t,.005f,.1f,0};
 Mechanical_Observe(&capture,t+10U,t,1000U,4,20.f,0,&c,1);
}
assert(capture.count==128 && !capture.flags && capture.points[0].samples==64);
assert(fabsf(capture.points[0].iq_mean_a-.1f)<1e-6f);
assert(fabsf(capture.points[0].iq_matched_mean_a-.1f)<1e-6f);
MechanicalCapture before=capture;
Mechanical_Observe(&capture,0,0,0,0,NAN,1,&c,0);
assert(!memcmp(&before,&capture,sizeof capture));
Mechanical_Reset(&capture);assert(!capture.count && capture.generation==2);
Mechanical_Observe(&capture,100,100,1000,0,20,0,&c,0);
assert(capture.flags&MEC_NO_CURRENT);
capture.raw_sum=INT32_MAX;
Mechanical_Observe(&capture,101,101,1,1,20,0,&c,0);
assert(capture.flags&MEC_RANGE);assert(capture.raw_sum==INT32_MAX);
MechanicalNormalizedModel model={.004f,.002f,.08f,.01f,31.415926f,2.f,1};
MechanicalDobShadow s={0};
for(unsigned i=0;i<1000;i++)MechanicalDob_Observe(&s,&model,.18f,20.f,.001f,1,0);
assert(s.valid && fabsf(s.disturbance_a-.05f)<1e-5f);
MechanicalDob_Reset(&s,0);
for(unsigned i=0;i<1000;i++){
 float w=10.f+2.f*i*.001f,iq=.004f*2.f+.002f*w+.08f+.01f;
 MechanicalDob_Observe(&s,&model,iq,w,.001f,1,0);
}
assert(s.valid && fabsf(s.disturbance_a)<1e-5f);
MechanicalDob_Observe(&s,&model,0,0,.001f,1,0);assert(!s.valid && s.status==DOB_SHADOW_ZERO_SPEED);
MechanicalDob_Observe(&s,&model,NAN,20,.001f,1,0);assert(!s.valid && s.status==DOB_SHADOW_BAD_SAMPLE);
MechanicalDob_Observe(&s,&model,.2f,20,.001f,1,1);assert(!s.valid && s.status==DOB_SHADOW_FAULT);
model.qualified=0;MechanicalDob_Observe(&s,&model,.2f,20,.001f,1,0);
assert(!s.valid && s.status==DOB_SHADOW_UNCONFIGURED);
return 0;}
'''
        exe=ROOT/'tmp/mechanical-identification-host.exe'
        p=subprocess.run([str(compiler.GCC),'-std=c11','-Os','-Wall','-Wextra','-Werror',
            '-I',str(ROOT/'firmware_common'),str(ROOT/'firmware_common/mechanical_identification.c'),
            '-x','c','-','-o',str(exe)],input=code,text=True,capture_output=True)
        self.assertEqual(p.returncode,0,p.stdout+p.stderr)
        p=subprocess.run([str(exe)],text=True,capture_output=True)
        self.assertEqual(p.returncode,0,p.stdout+p.stderr)


if __name__=='__main__':unittest.main()
