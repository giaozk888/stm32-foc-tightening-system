"""Separate, software-only factorial optimisation. Preserve previous evidence."""
from pathlib import Path
import difflib
import hashlib
import json
import shutil
import subprocess
import prepare_load_gain as prior

ROOT=prior.ROOT;WORK=ROOT/'simulation/dob_simulink/load_gain_opt_work'
BASELINE=ROOT/'simulation/dob_simulink/load_gain_results/20261024_212550'
PROFILES={'adaptive':dict(id=1,floor=0,rise=1), 'fast':dict(id=2,floor=0,rise=5),
          'floor':dict(id=3,floor=.10,rise=1),'combined':dict(id=4,floor=.10,rise=5)}


def build():
    WORK.mkdir(exist_ok=True);m=json.loads((BASELINE/'manifest.json').read_text())
    for item in m['sources']+m['firmware_unchanged_pins']:
        f=Path(item['path'])
        if hashlib.sha256(f.read_bytes()).hexdigest()!=item['sha256']:raise ValueError('Baseline source changed: '+str(f))
    if hashlib.sha256(Path(m['dll']).read_bytes()).hexdigest()!=m['dll_sha256']:raise ValueError('Baseline DLL changed')
    original=(prior.NATIVE/'load_gain_policy.h').read_text();s=original
    s=s.replace('OFFLINE_LOAD_GAIN_POLICY_H','OFFLINE_LOAD_GAIN_OPT_POLICY_H')
    s=prior.once(s,'LoadGain_Step(LoadGainScheduler *s,LoadGainEvidence e)',
        'LoadGainOpt_Step(LoadGainScheduler *s,LoadGainEvidence e,uint32_t profile)')
    s=prior.once(s,'    if(!e.feedback_enabled||!cap){',
        '    float floor=fminf(cap,(profile==3U||profile==4U)?.10f:0.f);\n'
        '    float rise=(profile==2U||profile==4U)?5.f:1.f;\n    if(!e.feedback_enabled||!cap){')
    s=prior.once(s,'s->requested=s->active?cap:0;','s->requested=s->active?cap:floor;')
    s=prior.once(s,'s->requested>s->selected?1.f:2.5f','s->requested>s->selected?rise:2.5f')
    (WORK/'load_gain_opt_policy.h').write_text(s)
    diff=list(difflib.unified_diff(original.splitlines(),s.splitlines(),fromfile='frozen/load_gain_policy.h',tofile='generated/load_gain_opt_policy.h'))
    original=(prior.WORK/'load_gain_host.c').read_text();s=original
    s=prior.once(s,'#include "load_gain_policy.h"','#include "load_gain_opt_policy.h"')
    s=prior.once(s,'gain_adaptive=c[3]!=0;','gain_adaptive=isfinite(c[3])&&c[3]>=0&&c[3]<=4?(uint32_t)c[3]:0;')
    s=prior.once(s,'LoadGain_Step(&gains,ge)','LoadGainOpt_Step(&gains,ge,gain_adaptive)')
    (WORK/'load_gain_opt_host.c').write_text(s)
    shutil.copyfile(prior.WORK/'load_gain_dob_host.c',WORK/'load_gain_dob_host.c')
    diff+=list(difflib.unified_diff(original.splitlines(),s.splitlines(),fromfile='frozen/load_gain_host.c',tofile='generated/load_gain_opt_host.c'))
    (WORK/'reviewed_opt_diff.patch').write_text('\n'.join(diff)+'\n')
    sources=[WORK/'load_gain_opt_host.c']+[prior.COMMON/n for n in (
        'mechanical_dob_monitor.c','speed_scurve.c','speed_accel_feedforward.c','speed_friction_compensation.c',
        'tightening_intent_fsm.c','dob_trend_shadow.c','tighten_params.cpp')]
    objects=[]
    for src in sources:
        obj=WORK/(src.name+'.o');objects.append(obj);cpp=src.suffix=='.cpp'
        cc=prior.old.reviewed.GCC.with_name('g++.exe') if cpp else prior.old.reviewed.GCC
        subprocess.run([str(cc),'-std=c++17' if cpp else '-std=c11','-O2','-Wall','-Wextra','-Werror',
            '-include',str(prior.NATIVE/'host_compat.h'),'-I',str(prior.COMMON),'-I',str(prior.NATIVE),
            *['-D'+f for f in m['flags']],'-c',str(src),'-o',str(obj)],check=True)
    dll=WORK/'load_gain_opt_host.dll'
    subprocess.run([str(prior.old.reviewed.GCC.with_name('g++.exe')),'-shared',*map(str,objects),'-lm','-o',str(dll)],check=True)
    files=[Path(f['path']) for f in m['sources']]+[WORK/'load_gain_opt_policy.h',WORK/'load_gain_opt_host.c',WORK/'load_gain_dob_host.c',Path(__file__)]
    files += [ROOT/'simulation/dob_simulink'/f for f in ('build_load_gain_opt.m','run_load_gain_opt.m','plot_load_gain_opt.m')]
    files += [ROOT/'tools/report_load_gain_opt.py']
    m.update(dll=str(dll),dll_sha256=hashlib.sha256(dll.read_bytes()).hexdigest(),profiles=PROFILES,
        baseline_results=str(BASELINE),baseline_manifest_sha256=hashlib.sha256((BASELINE/'manifest.json').read_bytes()).hexdigest(),
        sources=[dict(path=str(f),sha256=hashlib.sha256(f.read_bytes()).hexdigest()) for f in files if f.is_file()],
        variants=['off','fixed','adaptive','fast','floor','combined'])
    (WORK/'manifest.json').write_text(json.dumps(m,indent=2)+'\n')
    print('BUILT separate opt DLL: floor0/.10 x rise1/5 per s; gain ceiling .25; original evidence preserved')


if __name__=='__main__':build()
