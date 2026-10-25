"""Generate an audited, software-only derivative of the existing C host.
No production sources or previous DLLs are overwritten; no device APIs.
"""
from pathlib import Path
import difflib
import hashlib
import json
import subprocess
import prepare_load_speed as old

ROOT=old.ROOT;NATIVE=old.NATIVE;COMMON=old.COMMON
WORK=ROOT/'simulation/dob_simulink/load_gain_work'
EXTRA=('gain_max gain_requested gain_selected gain_active gain_reason gain_quality_valid '
       'gain_high_us gain_release_us gain_transitions gain_updates gain_credit_us gain_last_good_us '
       'feedback_source_qualified gain_observer_source_us').split()


def once(source,before,after):
    if source.count(before)!=1:raise ValueError('Reviewed host anchor changed: '+before[:60])
    return source.replace(before,after)


def generate():
    WORK.mkdir(exist_ok=True)
    original=(NATIVE/'dob_host.c').read_text()
    # Mirror the actual MCU SAT128 fresh-compensation veto, for ALL variants.
    source=once(original,'monitor.current.valid&&monitor.running&&!monitor.frozen&&',
        'monitor.current.valid&&monitor.running&&!monitor.frozen&&\n                !(monitor.current.status&DOB_MONITOR_SATURATED)&&')
    (WORK/'load_gain_dob_host.c').write_text(source)
    diff=list(difflib.unified_diff(original.splitlines(),source.splitlines(),fromfile='original/dob_host.c',tofile='generated/load_gain_dob_host.c'))
    original=(NATIVE/'load_speed_host.c').read_text();source=original
    source=once(source,'#include "dob_host.c"','#include "load_gain_dob_host.c"')
    source=once(source,'#define LOAD_SPEED_NY 66','#define LOAD_SPEED_NY 80')
    source=once(source,'static TighteningFsm process;',
        '#include "load_gain_policy.h"\nstatic LoadGainScheduler gains;\nstatic uint32_t gain_adaptive;\nstatic float gain_cap;\n'
        'static void gain_config(const double *c){gain_adaptive=c[3]!=0;gain_cap=isfinite(c[1])?fminf(.25f,fmaxf(0,(float)c[1])):0;}\n'
        'static TighteningFsm process;')
    source=once(source,'    uint32_t started;','    uint32_t started;\n    LoadGainScheduler gains;uint32_t gain_adaptive;float gain_cap;')
    source=once(source,'s.started=wrapper_started;s.time=wrapper_time;',
        's.started=wrapper_started;s.time=wrapper_time;s.gains=gains;s.gain_adaptive=gain_adaptive;s.gain_cap=gain_cap;')
    source=once(source,'wrapper_time=s.time;',
        'wrapper_time=s.time;gains=s.gains;gain_adaptive=s.gain_adaptive;gain_cap=s.gain_cap;')
    source=once(source,'{base_host_configure(c);}','{base_host_configure(c);gain_config(c);}')
    source=once(source,'base_host_reset(c);classification=',
        'base_host_reset(c);gains=(LoadGainScheduler){0};gain_config(c);classification=')
    source=once(source,'    double v[10];',
        '    uint32_t fresh=monitor.current.valid&&monitor.running&&!monitor.frozen&&\n'
        '        !(monitor.current.status&DOB_MONITOR_SATURATED)&&now+20-monitor.current.sample_us<=2000U&&\n'
        '        DobObserve10_FeedbackSpeedQualified(monitor.current.omega_rad_s);\n'
        '    uint32_t quality=fresh&&classification.valid&&now-classification.last_call<=2000U;\n'
        '    LoadGainEvidence ge={now,process.state,intent.control_mode==CONTROL_SPEED,protection!=TF_REASON_NONE,\n'
        '        feedback.enabled,gain_adaptive,quality,classification.state,classification.trend_valid,classification.trend_state,classification.mean,gain_cap};\n'
        '    dob_host_gain=LoadGain_Step(&gains,ge);\n'
        '    uint32_t consumed_source=monitor.current.sample_us;\n'
        '    double v[10];')
    source=once(source,'out[64]=contact_held;out[65]=reacquire_us;',
        'out[64]=contact_held;out[65]=reacquire_us;\n'
        '    double gain_extra[]={gain_cap,gains.requested,gains.selected,gains.active,gains.reason,quality,\n'
        '        gains.high_us,gains.release_us,gains.transitions,gains.updates,gains.credit_us,gains.last_good_us,fresh,consumed_source};\n'
        '    memcpy(out+66,gain_extra,sizeof gain_extra);')
    (WORK/'load_gain_host.c').write_text(source)
    diff+=list(difflib.unified_diff(original.splitlines(),source.splitlines(),fromfile='original/load_speed_host.c',tofile='generated/load_gain_host.c'))
    (WORK/'reviewed_host_diff.patch').write_text('\n'.join(diff)+'\n')


def build():
    generate();sources=[WORK/'load_gain_host.c']+[COMMON/name for name in (
        'mechanical_dob_monitor.c','speed_scurve.c','speed_accel_feedforward.c','speed_friction_compensation.c',
        'tightening_intent_fsm.c','dob_trend_shadow.c','tighten_params.cpp')]
    flags=old.FLAGS+['DOB_LOAD_SPEED_CONTACT_HOLD=1'];objects=[]
    for src in sources:
        obj=WORK/(src.name+'.o');objects.append(obj);cpp=src.suffix=='.cpp'
        compiler=old.reviewed.GCC.with_name('g++.exe') if cpp else old.reviewed.GCC
        subprocess.run([str(compiler),'-std=c++17' if cpp else '-std=c11','-O2','-Wall','-Wextra','-Werror',
            '-include',str(NATIVE/'host_compat.h'),'-I',str(COMMON),'-I',str(NATIVE),
            *['-D'+f for f in flags],'-c',str(src),'-o',str(obj)],check=True)
    dll=WORK/'load_gain_host.dll'
    subprocess.run([str(old.reviewed.GCC.with_name('g++.exe')),'-shared',*map(str,objects),'-lm','-o',str(dll)],check=True)
    files=sources+list(COMMON.glob('*.h'))+[NATIVE/f for f in ('dob_host.c','load_speed_host.c','load_gain_policy.h',
        'load_speed_contact_plant_sfun.c','dob_controller_sfun.c','dob_loader.h')]+[WORK/'load_gain_dob_host.c']
    files += [ROOT/'simulation/dob_simulink'/f for f in ('build_load_gain.m','run_load_gain.m','load_speed_inputs.m','build_load_speed.m')]
    files += [Path(__file__),ROOT/'tools/report_load_gain.py']
    # Evidence pins: firmware source/build definitions and the exact hardware-tested A/BINARY remain unchanged.
    firmware=[*COMMON.glob('*.c'),*COMMON.glob('*.h'),*COMMON.glob('*.inc')]
    firmware += [ROOT/project/name for project in ('foc2_app_a','foc2_app_b') for name in ('Core/Src/main.c','CMakeLists.txt','CMakePresets.json')]
    m=dict(output_names=old.BASE+old.EXTRA+['contact_held','contact_reacquire_us']+EXTRA,input_names=old.INPUT,
        dll=str(dll),dll_sha256=hashlib.sha256(dll.read_bytes()).hexdigest(),flags=flags,
        plant=[.000386049,.00155158,.11945168237076952,.0005496600325149542,.001],
        seeds=[1,2,3,4,5,61,62,63,64,65],hardware_access=False,physical_performance_validated=False,
        max_gain=.25,rise_gain_per_s=1,fall_gain_per_s=2.5,speed_scheduling=False,
        sources=[dict(path=str(f),sha256=hashlib.sha256(f.read_bytes()).hexdigest()) for f in files if f.is_file()],
        firmware_unchanged_pins=[dict(path=str(f),sha256=hashlib.sha256(f.read_bytes()).hexdigest()) for f in firmware if f.is_file()])
    assert len(m['output_names'])==80
    (WORK/'manifest.json').write_text(json.dumps(m,indent=2)+'\n')
    print('BUILT software-only gain scheduler;80 outputs;original controllers reused;SAT128 gate aligned with MCU')


if __name__=='__main__':build()
