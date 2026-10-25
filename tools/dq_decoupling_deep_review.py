"""Complete file-only sensitivity review of the saved dq OFF/ON experiment.

Uses real C fast trig/SVPWM/window quantization in a HOST-only counterfactual
angle sweep. This is not a board sweep, plant replay or a fitted motor model.
No firmware, controller parameter, device or boot-selection mutation.
"""
import argparse
import ctypes as ct
import hashlib
import json
import math
from pathlib import Path
from app_a_source_layout import read_app_source
import re
import subprocess
import zlib
import dq_decoupling_audit_report as audit
from current_pi_compare import GCC

ROOT=Path(__file__).resolve().parents[1]
OFF=ROOT/'tmp/dq-fsm-run-1792579105569898700.json'
ON=ROOT/'tmp/dq-fsm-run-1792579317512317700.json'


def handoff():
    """Files-only identity manifest; it grants no permission to actuate."""
    receipt=ROOT/'tmp/dq-fsm-restore-1792579402223585900.json'
    restored=json.loads(receipt.read_text())
    flash=Path(restored['final_capture']).read_bytes()
    expected='464aae9dd445156eda51ce39ff2d148bfe50759ff4da0d56e28de05c0f3848f9'
    if len(flash)!=512*1024 or hashlib.sha256(flash).hexdigest()!=expected:
        raise ValueError('Exact historical B916 saved restoration required')
    b=flash[0x40000:0x40000+227964]
    if zlib.crc32(b)!=627317606:raise ValueError('Historical confirmed B payload mismatch')
    images=[]
    for mode,preset in enumerate(('DqAuditCurrent','DqAuditReverseD','DqAuditReverseQ','DqAuditReverseBoth')):
        image=ROOT/f'foc2_app_a/build/{preset}/foc2.bin';elf=image.with_suffix('.elf')
        data=image.read_bytes()
        definitions=json.loads((image.parent/'compile_commands.json').read_text())
        cmd=next(c['command'] for c in definitions if c['file'].endswith('/Core/Src/main.c'))
        for flag in ('-DFOC_DQ_AUDIT_ENABLE=1','-DDECOUPLING_SIGN_TEST=1',
                     f'-DDECOUPLING_SIGN_MODE={mode}','-DFOC_DQ_LD_H=0.00002003f',
                     '-DFOC_DQ_LQ_H=0.00001118f','-DFOC_ONE_CYCLE_PWM_PIPELINE=1',
                     '-DSPEED_FRICTION_I_A=0.105f','-DSPEED_ACCEL_FF_KA_A_PER_RPM_S=0.0001875f'):
            if flag+' ' not in cmd:raise ValueError('Exact diagnostic/unchanged control flag required: '+flag)
        reset=int.from_bytes(data[4:8],'little')&~1
        if not 0x08008000<=reset<0x08040000 or len(data)>0x38000:
            raise ValueError('Non-A or oversized image')
        if b'DQA R seq=' in data or b'DQA R seq=' not in elf.read_bytes():
            raise ValueError('Tokenized log dictionary placement mismatch')
        images.append(dict(preset=preset,sign_mode=mode,bin=str(image),elf=str(elf),bytes=len(data),
            bin_sha256=hashlib.sha256(data).hexdigest(),elf_sha256=hashlib.sha256(elf.read_bytes()).hexdigest()))
    return dict(file_only=True,board_state_now='NOT_RECHECKED',
        historical_restore_receipt=str(receipt),historical_flash_sha256=expected,
        confirmed_B_payload_bytes=len(b),confirmed_B_payload_sha256=hashlib.sha256(b).hexdigest(),
        confirmed_B_slot_sha256=hashlib.sha256(flash[0x40000:0x7e800]).hexdigest(),images=images,
        old_pinned_board_executor_compatible=False,
        next_manual_batch=['mode0 OFF','mode0 ON','mode0 ON repeat','mode0 OFF repeat'],
        conditional_manual_sign_runs=['reverse d only','reverse q only','reverse both'],
        prerequisites=['fresh operator/power/fixture confirmation before hardware operations',
            'review exact diagnostic-image staging/restore adapter; never blindly replace old executor hashes',
            'same initial rotor orientation and existing calibration behavior; save calibration values',
            'same recipe/temperature/load; preserve all existing protection and lease',
            'new boot per run: audit aggregates are one-run-per-reset',
            'quality anomalies retained; independent protection or unverifiable shutdown stops the group'],
        required_capture=['four same-seq DQA frame rows with first500ms coverage',
            'final same-halt complete Flash/SRAM, A VTOR and exact ELF',
            'existing friction/accel metrics and actual CCR/deadline counters',
            'initial encoder angle and zero offsets; no fabricated common initial angle'],
        no_auto_flash=True,no_auto_start=True,no_auto_sign_sweep=True)


def compile_quantizer(out):
    source=read_app_source(ROOT/'foc2_app_a/Core/Src/main.c')
    # Take the unchanged real inverse Park -> centered SVPWM arithmetic.
    start=source.index('    v_alpha = vd * c - vq * s;')
    body=source[start:source.index('    PWM_SetDuty(du, dv, dw);',start)]
    for required in ('#define ADC_VREF_MV 3300U','#define ADC_FULL_SCALE 4095U',
                     '#define CURRENT_GAIN_MV_PER_A 120U','#define FOC_DC_BUS_V 12.0f',
                     'htim1.Init.Period = 4249;'):
        if not re.search(r'\s+'.join(re.escape(x) for x in required.split()),source):
            raise ValueError('Source configuration changed: '+required)
    commands=json.loads((ROOT/'foc2_app_a/build/DqAuditCurrent/compile_commands.json').read_text())
    cmd=next(x['command'] for x in commands if x['file'].endswith('/Core/Src/main.c'))
    for flag in ('-DFOC_ADC_SETTLE_TICKS=85','-DFOC_ADC_RC_MIN_LOW_ON_TICKS=1700',
                 '-DFOC_ADC_SENSE_TOPOLOGY=2','-DFOC_PWM_COMMON_MODE_ENABLE=1'):
        if flag+' ' not in cmd:raise ValueError('PWM counterfactual configuration drift: '+flag)
    header=(ROOT/'firmware_common/foc_adc_timing_stm32.h').read_text()
    timing=(ROOT/'firmware_common/foc_adc_timing_stm32.c').read_text()
    if ('#define FOC_ADC_TIMER_ARR 4249U' not in header or
        '#define FOC_ADC_TRIGGER_LATENCY_MAX_TICKS 14U' not in header or
        'FOC_ADC_TRIGGER_LATENCY_MAX_TICKS, 50U,' not in timing):
        raise ValueError('PWM timing counterfactual ABI drift')
    code='''#include <stdint.h>
#include <math.h>
#include "foc_fast_trig.h"
#include "foc_pwm_common_mode.h"
#define FocProfile_Mark(x) ((void)0)
#define FOC_DC_BUS_V 12.0f
__declspec(dllexport) int quantize(float vd,float vq,float theta,int *result){
float s,c,v_alpha,v_beta,vu,vv,vw,vmax,vmin,voffset,du,dv,dw;
if (!isfinite(vd)||!isfinite(vq)||!FocFast_SinCos(theta,&s,&c)) return 2;
float magnitude=vd*vd+vq*vq;
if (magnitude>1.60f*1.60f){float scale=1.60f/sqrtf(magnitude);vd*=scale;vq*=scale;}
'''+body+'''
const FocWindowConfig cfg={4249,85,85,14,50,FOC_SENSE_LOW_SIDE_UV,1700,FOC_SAMPLE_LATE_BEFORE_PEAK};
FocWindowPlan plan;int16_t offset=0;
int status=FocPwmCommonMode_Plan(&cfg,du,dv,dw,4184,85,&plan,&offset);
if (!status){for(int n=0;n<3;++n) result[n]=plan.phase[n];
result[3]=plan.trigger;result[4]=plan.slack_ticks;result[5]=offset;}
return status;}
'''
    out=Path(out);out.mkdir(parents=True,exist_ok=True)
    dll=out/'dq-native-quantizer.dll'
    cmd=[str(GCC),'-std=c11','-O2','-shared','-Wall','-Wextra','-Werror',
         '-I',str(ROOT/'firmware_common'),'-x','c','-',
         str(ROOT/'firmware_common/foc_fast_trig.c'),
         str(ROOT/'firmware_common/foc_pwm_common_mode.c'),
         str(ROOT/'firmware_common/foc_adc_window.c'),'-o',str(dll)]
    p=subprocess.run(cmd,input=code,capture_output=True,text=True)
    if p.returncode:raise RuntimeError(p.stdout+p.stderr)
    library=ct.CDLL(str(dll.resolve()))
    library.quantize.argtypes=[ct.c_float]*3+[ct.POINTER(ct.c_int)]
    library.quantize.restype=ct.c_int
    return library


def quantization_sensitivity(receipt,native,angles=720):
    if angles<4:raise ValueError('At least four offline angles required')
    voltage=[x['values'] for x in receipt.get('dq_samples',[])
             if x['command'].endswith('VOLTAGE') and x['values'].get('VALID')=='1'
             and x['values'].get('SAT')=='0']
    changed=0;line_changed=0;n=0;max_phase=0;max_line=0;errors=0
    for f in voltage:
        vd0,vq0,vd1,vq1=[int(f[k])*1e-6 for k in ('VD_PI_UV','VQ_PI_UV','VD_UV','VQ_UV')]
        for k in range(angles):
            theta=-math.pi+2*math.pi*k/angles
            before=(ct.c_int*6)();after=(ct.c_int*6)()
            a=native.quantize(vd0,vq0,theta,before);b=native.quantize(vd1,vq1,theta,after)
            if a or b:errors+=1;continue
            n+=1;d=[after[i]-before[i] for i in range(3)]
            changed+=any(d);line_delta=[d[0]-d[1],d[1]-d[2],d[2]-d[0]]
            line_changed+=any(line_delta)
            max_phase=max(max_phase,*map(abs,d));max_line=max(max_line,*map(abs,line_delta))
    return dict(kind='HOST_COUNTERFACTUAL_NOT_MEASURED_CCR',saved_voltage_points=len(voltage),
        synthetic_angles_per_point=angles,accepted_counterfactuals=n,planner_rejects=errors,
        any_phase_ccr_changed=changed,line_to_line_changed=line_changed,
        phase_changed_percent=100*changed/n if n else None,
        max_phase_delta_ticks=max_phase,max_line_delta_ticks=max_line,
        caveat='Freeze each saved PI voltage and vary unrecorded theta. Does not replay feedback, integrator history, actual rotor orientation or physical dead time. Saved voltages have 1uV wire quantization.')


def startup_evidence(receipt):
    status=[s for s in receipt.get('samples',[]) if s['status'].get('BUSY')=='1']
    timeline=[]
    for s in status:
        if s['elapsed_s']>.55:continue
        f=s['status']
        timeline.append(dict(host_elapsed_ms=1000*s['elapsed_s'],
            position_deg=float(f['POS'].removesuffix('deg')),
            speed_ctrl_rpm=float(f['CTRL'].removesuffix('rpm')),
            speed_detect_rpm=float(f['DET'].removesuffix('rpm'))))
    first=next((s for s in timeline if abs(s['position_deg'])>=.1),None)
    frc={}
    for row in receipt.get('tokenized_decoded',[]):
        line=row['decoded'];m=re.search(r'\bFRC ([RCI]) ',line)
        if not m:continue
        f=audit.fields(line);seq=int(f['seq'])
        r=frc.setdefault(seq,dict(parts=set(),seq=seq));r['parts'].add(m[1])
        r.update({k:float(v) for k,v in f.items() if k!='seq'})
    points=[{k:v for k,v in r.items() if k!='parts'} for r in frc.values() if r['parts']==set('RCI')]
    return dict(first_status_position_ge_0p1deg=first,first_550ms_status=timeline,
        existing_start_metric_ms=receipt['friction_metrics']['POS']['START_MS'],
        definition='command direction: speed_ref >2rpm AND filtered speed >=2rpm continuously for50ms; not first mechanical motion',
        joined_1khz_source_log_snapshots=points,
        sampling_note='FRC rows are coherent same-seq 100ms snapshots, NOT a full 1kHz trace. STATUS uses host receive time.')


def sensitivity_scales():
    count_a=3300/(4095*120)
    dq_offset=count_a*math.sqrt(1+1/3)
    wc=2*math.pi*300;ki=.78*wc;dt=50e-6
    return dict(configured_bus_v=12.,period_scale_counts=4250,
        command_scale_volts_per_ccr_tick=12/4250,
        physical_ideal_center_aligned_volts_per_tick_approx=12/4249,
        single_phase_amp_per_adc_count=count_a,
        one_U_offset_count_dq_vector_amplitude_a=dq_offset,
        one_U_offset_count_single_update_PI_d_bound_v=(20.03e-6*wc+ki*dt)*dq_offset,
        one_U_offset_count_single_update_PI_q_bound_v=(11.18e-6*wc+ki*dt)*dq_offset,
        one_U_offset_count_equivalent_iq_ref_fraction=dq_offset/.5,
        encoder_angle_lsb_deg=360/16384,
        nominal_encoder_instant_rpm_lsb_at_1ms=60/(16384*.001),
        warning='Analytical scale comparison, not actual phase/current error or startup prediction. PI voltage bounds are first unsaturated update with fixed prior integrators, not accumulated drift.')


def review(off,on,native):
    result=dict(board_actions=0,firmware_parameter_writes=0,comparison=audit.compare(off,on),
        off_start=startup_evidence(off),on_start=startup_evidence(on),scales=sensitivity_scales(),
        off_pwm_counterfactual=quantization_sensitivity(off,native),
        on_pwm_counterfactual=quantization_sensitivity(on,native),
        same_image=off.get('image_sha256')==on.get('image_sha256'),
        same_recipe=off.get('effective_ram_recipe')==on.get('effective_ram_recipe'),
        zero_offset_difference_counts={axis:on['zero'][axis]-off['zero'][axis] for axis in ('zero_u','zero_v')},
        common_mode=dict(off=off.get('common_mode'),on=on.get('common_mode')),handoff=handoff(),
        conclusion='No demonstrated dq sign/unit/limit bug. Startup metric is not first motion; sub-CCR voltage and calibration/initial-condition sensitivity are plausible contributors, NOT proven causes. Missing first500ms same-frame voltage evidence requires a new supervised capture; do not retune gains/sign/zero.')
    return result


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--off',type=Path,default=OFF);p.add_argument('--on',type=Path,default=ON)
    p.add_argument('--host-build',type=Path,default=ROOT/'tmp/dq-deep-host')
    a=p.parse_args();native=compile_quantizer(a.host_build)
    print(json.dumps(review(json.loads(a.off.read_text()),json.loads(a.on.read_text()),native),
                     indent=2,allow_nan=False))


if __name__=='__main__':main()
