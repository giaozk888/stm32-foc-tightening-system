"""Offline actual C PI replay against an ASSUMED locked-rotor RL plant.

No device access, no parameter write. Uses the existing one-cycle pending
command and assumed half-cycle latch geometry, not a measured plant response.
"""
import argparse
import ctypes
import json
import math
from pathlib import Path
from app_a_source_layout import read_app_source
import subprocess

ROOT=Path(__file__).resolve().parents[1]
GCC=Path(r'D:\Qt\Tools\mingw1310_64\bin\gcc.exe')


class State(ctypes.Structure):
    _fields_=[('d',ctypes.c_float),('q',ctypes.c_float)]


def pi_source():
    source=read_app_source(ROOT/'foc2_app_a/Core/Src/main.c',encoding='utf-8')
    start=source.index('    err_d = foc_id_ref_A - id_A;')
    end=source.index('#endif /* Exclusive voltage diagnostic, original current PI otherwise. */',start)
    return source[start:end]


def compile_pi(enabled,out):
    out.mkdir(parents=True,exist_ok=True)
    library=out/('pi_identified.dll' if enabled else 'pi_legacy.dll')
    code='''#include <math.h>
#define FOC_CURRENT_KP_V_PER_A .080f
#define FOC_CURRENT_KI_V_PER_AS 188.0f
#include "current_pi_identified_candidate.h"
#define FOC_TS_S .00005f
#define FOC_CURRENT_FAULT_TRACE_ENABLE 0
#define FOC_INTEGRATOR_LIMIT_V .75f
#define FOC_VOLTAGE_LIMIT_V 1.60f
typedef struct {float d,q;} State;
static float ClampFloat(float v,float lo,float hi){return v<lo?lo:v>hi?hi:v;}
__declspec(dllexport) void gains(float *v) {
v[0]=FOC_CURRENT_KP_D_V_PER_A;v[1]=FOC_CURRENT_KP_Q_V_PER_A;
v[2]=FOC_CURRENT_KI_D_V_PER_AS;v[3]=FOC_CURRENT_KI_Q_V_PER_AS;
v[4]=CURRENT_PI_CANDIDATE_RS_OHM;v[5]=CURRENT_PI_CANDIDATE_LD_H;v[6]=CURRENT_PI_CANDIDATE_LQ_H;
}
__declspec(dllexport) void step(State *state,float foc_id_ref_A,float foc_iq_ref_A,
float id_A,float iq_A,float *voltage) {
float foc_int_d_V=state->d,foc_int_q_V=state->q;
float err_d,err_q,vd,vq,mag2,limit2;
'''+pi_source()+'''
state->d=foc_int_d_V;state->q=foc_int_q_V;voltage[0]=vd;voltage[1]=vq;
}
'''
    p=subprocess.run([str(GCC),'-std=c11','-O2','-shared','-Wall','-Wextra','-Werror',
        '-DFOC_CURRENT_PI_IDENTIFIED_ENABLE='+str(int(enabled)),
        '-I',str(ROOT/'firmware_common'),'-x','c','-','-o',str(library)],
        input=code,capture_output=True,text=True)
    if p.returncode:raise RuntimeError(p.stdout+p.stderr)
    dll=ctypes.CDLL(str(library.resolve()))
    dll.step.argtypes=[ctypes.POINTER(State)]+[ctypes.c_float]*4+[ctypes.POINTER(ctypes.c_float)]
    dll.step.restype=None
    dll.gains.argtypes=[ctypes.POINTER(ctypes.c_float)];dll.gains.restype=None
    values=(ctypes.c_float*7)();dll.gains(values)
    return dll,list(values)


def simulate(dll,gains,axis,target,rs_scale=1.,l_scale=1.,noisy=False):
    # ADC(k) reads before entry commit; pending(k-1) latches at following bottom.
    # Interval k..k+1: applied old voltage for 25us, then previous pending 25us.
    dt=50e-6;rs=gains[4]*rs_scale;inductance=gains[5+axis]*l_scale
    state=State();voltage=(ctypes.c_float*2)();current=[0.,0.]
    applied=[0.,0.];pending=[0.,0.];trace=[]
    for k in range(1600):
        t=k*dt;ref=target if .005<=t<.045 else 0.
        measurement=current.copy()
        if noisy:
            measurement[axis]+=.005*math.sin(2*math.pi*1700*t)
        held=noisy and k%100==17  # sensitivity, NOT a discriminator simulation
        if not held:
            dll.step(ctypes.byref(state),ref if axis==0 else 0.,ref if axis==1 else 0.,
                     *measurement,voltage)
            generated=list(voltage)
        else:generated=pending.copy()  # real policy: freeze PI and pending
        trace.append(dict(t=t,ref=ref,current=current[axis],integrator=state.d if axis==0 else state.q,
                          voltage=generated[axis],held=held))
        for ax in (0,1):
            l=gains[5+ax]*l_scale;a=math.exp(-dt*.5*rs/l)
            current[ax]=a*current[ax]+(1-a)*applied[ax]/rs
            current[ax]=a*current[ax]+(1-a)*pending[ax]/rs
        applied=pending;pending=generated
    on=[p for p in trace if .005<=p['t']<.045]
    sign=1 if target>0 else -1
    overshoot=max(0.,max(sign*p['current'] for p in on)-abs(target))/abs(target)*100
    rise=next((1000*(p['t']-.005) for p in on if sign*p['current']>=.9*abs(target)),None)
    failures=[i for i,p in enumerate(on) if abs(p['ref']-p['current'])>.02*abs(target)]
    settle=(1000*(on[failures[-1]+1]['t']-.005) if failures and failures[-1]+1<len(on)
            else 0. if not failures else None)
    return dict(axis='d' if axis==0 else 'q',target_a=target,
        assumed_rs_ohm=rs,assumed_inductance_h=inductance,
        noisy_5mA_and_hold=noisy,rise_to_90_ms=rise,settling_2percent_ms=settle,
        overshoot_percent=overshoot,mean_abs_error_mA=1000*sum(abs(p['ref']-p['current']) for p in on)/len(on),
        peak_abs_current_a=max(abs(p['current']) for p in trace),
        peak_integrator_v=max(abs(p['integrator']) for p in trace),
        peak_axis_command_v=max(abs(p['voltage']) for p in trace),
        settled_mean_error_mA=1000*sum(abs(p['ref']-p['current']) for p in on[-200:])/200)


def compare(out):
    results=[]
    for enabled in (False,True):
        dll,gains=compile_pi(enabled,out)
        cases=[]
        scenarios=[(r,l,False) for r in (.5,1.,2.) for l in (.5,1.,2.)]+[(1.,1.,True)]
        for rs_scale,l_scale,noisy in scenarios:
            for axis in (0,1):
                for target in (.1,.35,-.35):
                    cases.append(simulate(dll,gains,axis,target,rs_scale,l_scale,noisy))
        results.append(dict(pi='IDENTIFIED' if enabled else 'LEGACY',
            kp_d=gains[0],kp_q=gains[1],ki_d=gains[2],ki_q=gains[3],cases=cases))
    return dict(offline_only=True,board_test=False,qualified=False,automatic_parameter_write=False,
        assumption='Decoupled locked-rotor RL, assumed Rs/Ld/Lq, 50us pipeline + half-cycle latch; not measured accuracy/stability',
        results=results)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--build-dir',type=Path,default=ROOT/'tmp/current-pi-host')
    args=parser.parse_args()
    print(json.dumps(compare(args.build_dir),indent=2))
