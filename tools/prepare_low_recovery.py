"""Compile an isolated software-only estimator A/B and independent inputs."""
import csv
import hashlib
import json
import math
from pathlib import Path
import random
import struct
import subprocess
ROOT=Path(__file__).resolve().parents[1]
WORK=ROOT/'simulation/dob_simulink/low_recovery_work'
NATIVE=ROOT/'simulation/dob_simulink/native'
COMMON=ROOT/'firmware_common'
GCC=Path('D:/Qt/Tools/mingw1310_64/bin/gcc.exe')
FLAGS=['FOC_DOB_SPIKE_ADMISSION=1','FOC_DOB_ADMISSION_START_GUARD=1','FOC_DOB_DIRECT_JUMP_REJECT=1',
 'FOC_DOB_RECOVERABLE_ADMISSION=1','FOC_DOB_PERSISTENT_QUALITY=1','FOC_DOB_ID_PRE_LPF_QUALITY=1',
 'FOC_DOB_NORMAL_CONTROL=1','FOC_DOB_CONTACT20_OBSERVE10=1','FOC_DOB_FEEDBACK_CANDIDATE=1',
 'FOC_DOB_ID_TRACE=1','FOC_DOB_SATURATION_CONTINUE=1','FOC_DOB_WARMUP_AB=1',
 'DOB_WARMUP_DEFAULT_TAU=3U','DOB_ADMIT_JUMP_A=.200f','DOB_FB_GAIN=.25f']
OUT_NAMES='estimate_a valid status warm_elapsed_s shadow_comp_a feedback_state raw_reset_calls mode reason fast cold held_epochs confirm_epochs quiet_n abs_id_lpf filter_updated omega_lpf drive_lpf initialized running frozen feedback_valid_updates iq_meas_a id_meas_a low_max_us observations valid_samples rejected_samples quiet_start_us return_start_us low_start_us reserved0 reserved1'.split()
IN_NAMES='observed_us encoder_us dt_us omega_meas_rad_s id_meas_a iq_meas_a seq source_us published_us current_valid iq_saturated source_flags running protection_fault load_truth_a omega_true_rad_s'.split()
SCENARIOS=['no_low','short20','short60','short90','long150','reverse','spike','source_gap',
           'persistent_id','changed_load','noise','return_saturation','real_measurement','fault']
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def build():
    WORK.mkdir(exist_ok=True)
    for enabled,name,timeout in [(0,'baseline',150000),(1,'retain',150000),(1,'retain200',200000)]:
        cmd=[str(GCC),'-std=c11','-O2','-Wall','-Wextra','-Werror','-shared',
            '-include',str(NATIVE/'host_compat.h'),'-I',str(COMMON),'-I',str(NATIVE),
            *['-D'+f for f in FLAGS],'-DLOW_RECOVERY_ENABLED='+str(enabled),'-DOLR_RETURN_US='+str(timeout)+'U',
            str(NATIVE/'low_recovery_host.c'),str(COMMON/'mechanical_dob_monitor.c'),
            '-lm','-o',str(WORK/(name+'.dll'))]
        p=subprocess.run(cmd,capture_output=True,text=True)
        if p.returncode:raise RuntimeError(p.stderr)
    print('BUILT baseline/retain150/retain200 isolated DLLs; actual monitor/gates/feedback,3tau',flush=True)

def prepare():
    build();runs=[];dt=.001;a=.0003782906586526162;b=.0015676864325576986;ic=.11945168237076952;bias=.0005496600325149542
    events=list(csv.DictReader((ROOT/'simulation/dob_simulink/real_five/data/events.csv').open()))
    for name in SCENARIOS:
        for seed in [1,2,3,4,5,61,62,63,64,65]:
            rng=random.Random(18000+seed);n=7001;hold=.02 if name=='short20' else .09 if name=='short90' else .15 if name=='long150' else .06
            enter=3.1;leave=enter+hold;last=leave+.1
            w=[];truth=[]
            for k in range(n):
                t=k*dt;rpm=240.
                if name!='no_low':
                    if 3<=t<enter:rpm=240+(5-240)*(t-3)/.1
                    elif enter<=t<leave:rpm=5.
                    elif leave<=t<last:rpm=5+((-240 if name=='reverse' else 240)-5)*(t-leave)/.1
                    elif t>=last:rpm=-240. if name=='reverse' else 240.
                load=.2 if name!='no_low' and 3<=t<leave else .08 if name=='changed_load' and t>=leave else 0.
                w.append(rpm*math.pi/30);truth.append(load)
            rows=[]
            for k in range(n):
                t=k*dt;derivative=(w[min(k+1,n-1)]-w[max(0,k-1)])/(dt*(1 if k in (0,n-1) else 2))
                iq=a*derivative+b*w[k]+ic*(1 if w[k]>=0 else -1)+bias+truth[k]
                assert abs(iq)<.500001,'Independent physically consistent input must respect current range'
                noise=3 if name=='noise' else 1
                omega=w[k]+rng.gauss(0,.4*noise)*math.pi/30
                id_a=.005+rng.gauss(0,.003);iq_meas=iq+rng.gauss(0,.002*noise)
                if name=='spike' and abs(t-(enter+.02))<.0001:id_a=.7
                if name=='persistent_id' and enter<=t<enter+.08:id_a=.09
                valid=not(name=='source_gap' and enter+.02<=t<enter+.023)
                saturated=name=='return_saturation' and leave<=t<leave+.2
                fault=name=='fault' and t>=enter+.02
                enc=100000+k*1000
                rows.append([enc+20,enc,1000,omega,id_a,iq_meas,20*(k+1),enc-20,enc,int(valid),int(saturated),0,int(k<n-1),int(fault),truth[k],w[k]])
            if name=='real_measurement':
                pool=[1,2,3] if seed<=5 else [4,5]
                for start in [2.3+i*.192 for i in range(22)]:
                    source=rng.choice(pool)
                    for e in events:
                        if int(e['source_id'])!=source:continue
                        k=round((start+float(e['relative_us'])*1e-6)/dt)
                        if 0<=k<n:
                            rows[k][4]=float(e['id_raw_a']);rows[k][5]+=float(e['iq_residual_a'])
                            rows[k][3]+=float(e['speed_highpass_rpm'])*math.pi/30
            file=WORK/f'{name}_seed{seed:03d}.bin'
            with file.open('wb') as f:
                for row in rows:f.write(struct.pack('<16d',*row))
            runs.append(dict(scenario=name,seed=seed,input=str(file),sha256=sha(file),rows=n,
                low_nominal_ms=hold*1000,return_start_s=leave,return_settled_s=last))
    files=[COMMON/'mechanical_dob_monitor.c',COMMON/'mechanical_dob_shadow.h',COMMON/'dob_current_admission.h',
        COMMON/'dob_id_pre_lpf_quality.h',COMMON/'dob_feedback_candidate.h',NATIVE/'offline_low_recovery.h',
        NATIVE/'low_recovery_host.c',NATIVE/'low_recovery_sfun.c',
        ROOT/'foc2_app_a/Core/Src/main.c',ROOT/'foc2_app_b/Core/Src/main.c']
    from app_a_source_layout import app_source_files
    files += [p for p in app_source_files() if p not in files]
    manifest=dict(runs=runs,repeats=10,input_names=IN_NAMES,output_names=OUT_NAMES,flags=FLAGS,
        profiles=['baseline','retain','retain200'],
        dlls={p:dict(path=str(WORK/(p+'.dll')),sha256=sha(WORK/(p+'.dll'))) for p in ('baseline','retain','retain200')},
        sources=[dict(path=str(p),sha256=sha(p)) for p in files],hardware_access=False,
        policy=dict(max_low_ms=100,max_return_ms=dict(retain=150,retain200=200),quiet_ms=20,omega_range_rad_s=.5,drive_range_a=.010),
        acceptance=dict(max_valid_rmse_a=.012,max_valid_bias_a=.008,max_extra_shadow_comp_a=.005,
            require_no_valid_during_low=True,require_fallback_for_unsafe=True,require_recovery_not_slower=True),
        physical_performance_validated=False,
        semantics='Estimator-only Simulink A/B. Prescribed speed plus model-consistent current; independent load. Shadow compensation never drives the plant. Real-measurement noise is a hypothesis, not measured external torque.')
    (WORK/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    print('PREPARED',len(runs),'paired independent inputs; no firmware mutation',flush=True)
    return manifest
if __name__=='__main__':prepare()
