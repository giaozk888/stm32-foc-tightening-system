"""Build a separate offline contact-boundary experiment. No hardware access."""
import hashlib
import json
import subprocess
from pathlib import Path
import prepare_load_speed as old

ROOT=old.ROOT
WORK=ROOT/'simulation/dob_simulink/load_speed_contact_work'


def build():
    WORK.mkdir(exist_ok=True)
    pins=json.loads((WORK/'legacy_pins.json').read_text())
    legacy=WORK/'legacy_host.dll'
    assert hashlib.sha256(legacy.read_bytes()).hexdigest()==pins['legacy_dll_sha256']
    sources=[old.NATIVE/'load_speed_host.c']+[old.COMMON/name for name in (
        'mechanical_dob_monitor.c','speed_scurve.c','speed_accel_feedforward.c',
        'speed_friction_compensation.c','tightening_intent_fsm.c','dob_trend_shadow.c','tighten_params.cpp')]
    objects=[]
    flags=old.FLAGS+['DOB_LOAD_SPEED_CONTACT_HOLD=1']
    for src in sources:
        obj=WORK/(src.name+'.o');objects.append(obj)
        cpp=src.suffix=='.cpp';compiler=old.reviewed.GCC.with_name('g++.exe') if cpp else old.reviewed.GCC
        subprocess.run([str(compiler),'-std=c++17' if cpp else '-std=c11','-O2','-Wall','-Wextra','-Werror',
            '-include',str(old.NATIVE/'host_compat.h'),'-I',str(old.COMMON),'-I',str(old.NATIVE),
            *['-D'+f for f in flags],'-c',str(src),'-o',str(obj)],check=True)
    dll=WORK/'contact_host.dll'
    subprocess.run([str(old.reviewed.GCC.with_name('g++.exe')),'-shared',*map(str,objects),'-lm','-o',str(dll)],check=True)
    files=sources+list(old.COMMON.glob('*.h'))+[old.NATIVE/'dob_host.c',old.NATIVE/'load_speed_contact_plant_sfun.c',
        ROOT/'tools/prepare_load_speed_contact.py',ROOT/'tools/report_load_speed_contact.py']
    files += [ROOT/'simulation/dob_simulink'/name for name in (
        'build_load_speed_contact.m','run_load_speed_contact.m','load_speed_contact_inputs.m',
        'build_load_speed.m','load_speed_inputs.m')]
    from app_a_source_layout import app_source_files
    files += [p for p in app_source_files() if p not in files]
    manifest=dict(output_names=old.BASE+old.EXTRA+['contact_held','contact_reacquire_us'],
        legacy_output_names=old.BASE+old.EXTRA,input_names=old.INPUT,dll=str(dll),legacy_dll=str(legacy),
        legacy_dll_sha256=pins['legacy_dll_sha256'],flags=flags,seeds=[1,2,3,4,5,61,62,63,64,65],
        plant=[.000386049,.00155158,.11945168237076952,.0005496600325149542,.001],
        hardware_access=False,physical_performance_validated=False,
        sources=[dict(path=str(f),sha256=hashlib.sha256(f.read_bytes()).hexdigest()) for f in files if f.is_file()])
    (WORK/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    print('BUILT contact-hold66 outputs; frozen legacy64 outputs verified; hardware_access=False')


if __name__=='__main__':build()
