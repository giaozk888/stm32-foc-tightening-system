"""FILES ONLY: audit existing Ka windows; no board access or parameter writes.

100ms compressed windows cannot reconstruct a 20ms lag or the original 1kHz
waveforms. Lag scans and piecewise-constant current filtering are sensitivity
checks, NEVER a calibrated Ka or automatically chosen delay/sign.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import statistics
import ka_identification_report as identification

ROOT=Path(__file__).resolve().parents[1]
ELF=ROOT/'foc2_app_a/build/KaIdentificationDiagnostic/foc2.elf'
ELF_SHA='b8b587ac31cbebdc3901f75ee06c320236836bf956bcd39393568224775bc893'
BIN_SHA='cd9f970c4ddfb3ce8ddb9f2e13e1046441d5644bb05df01e493f726d570fb8be'
TAU_S=.020
LAGS=(-2,-1,0,1,2)


def regression(x,y,weights):
    if len(x)<8 or not len(x)==len(y)==len(weights):raise ValueError('At least 8 matched observations required')
    total=sum(weights);mx=sum(a*w for a,w in zip(x,weights))/total
    my=sum(a*w for a,w in zip(y,weights))/total
    xx=sum(w*(a-mx)**2 for a,w in zip(x,weights))
    if xx<=1e-20:return dict(n=len(x),ka=None,b=None,r2=None)
    slope=sum(w*(a-mx)*(v-my) for a,v,w in zip(x,y,weights))/xx;b=my-slope*mx
    sse=sum(w*(v-(slope*a+b))**2 for a,v,w in zip(x,y,weights))
    yy=sum(w*(v-my)**2 for v,w in zip(y,weights))
    return dict(n=len(x),ka=slope,b=b,r2=1-sse/yy if yy>1e-24 else None)


def held_current_filter(values,durations,tau=TAU_S):
    """Exact continuous LPF average ONLY for assumed constant input per block.

    This is NOT exact filtering of the original unrecorded current waveform.
    Warm-up starts from zero and all blocks are used before scored >=600ms.
    """
    state=0.;out=[]
    for v,t in zip(values,durations):
        if t<=0 or tau<=0:raise ValueError('Positive times required')
        decay=math.exp(-t/tau)
        out.append(v+(state-v)*tau/t*(1-decay))
        state=v+(state-v)*decay
    return out


def analyze(windows):
    if len(windows)!=24 or any(f['seq']!=i+1 or f['flags'] for i,f in enumerate(windows)):
        raise ValueError('Exactly 24 ordered quality-valid windows required for this five-run audit')
    if any(a['end_us']!=b['start_us'] for a,b in zip(windows,windows[1:])):
        raise ValueError('Contiguous windows required')
    durations=[((f['end_us']-f['start_us'])&0xffffffff)*1e-6 for f in windows]
    if any(not .09<=t<=.105 for t in durations):raise ValueError('Unexpected capture interval')
    accel=[(f['speed_end_rpm']-f['speed_start_rpm'])/t for f,t in zip(windows,durations)]
    current=[f['mean_iq_a']-f['mean_friction_a'] for f in windows]
    if any(not math.isfinite(v) for v in accel+current):raise ValueError('Nonfinite data')
    start=windows[0]['start_us']
    eligible=[i for i,f in enumerate(windows) if ((f['start_us']-start)&0xffffffff)>=600000
              and min(f['speed_start_rpm'],f['speed_end_rpm'])>=10]
    # One common index set for ALL lags: no improvement from changing n or
    # retaining just the window that makes a particular lag look good.
    common=[i for i in eligible if all(0<=i-len_shift<len(windows) for len_shift in LAGS)]
    scans=[]
    for lag in LAGS:
        scans.append(dict(lag_windows=lag,nominal_current_lead_ms=lag*100,
            **regression([accel[i] for i in common],[current[i-lag] for i in common],[durations[i] for i in common])))
    approximate=held_current_filter(current,durations)
    return dict(measurement_only=True,primary_unshifted_post_startup=regression(
            [accel[i] for i in eligible],[current[i] for i in eligible],[durations[i] for i in eligible]),
        common_window_sequences=[windows[i]['seq'] for i in common],lag_sensitivity=scans,
        approximate_current_lpf_20ms=regression([accel[i] for i in eligible],
            [approximate[i] for i in eligible],[durations[i] for i in eligible]),
        filter_assumption='Current-minus-friction constant within each recorded 100ms window, initial state zero. Sensitivity ONLY, not recovery of 1kHz current.',
        moving_windows=len(eligible),positive_measured_iq_windows=sum(windows[i]['mean_iq_a']>0 for i in eligible),
        min_window_mean_iq_a=min(windows[i]['mean_iq_a'] for i in eligible),
        measured_speed_filter_tau_ms=20,stored_endpoint_spacing_ms=statistics.mean(durations)*1000,
        exact_20ms_alignment_identifiable=False,auto_selected_delay=None,auto_selected_ka=None,
        lag_convention='positive lag pairs current from an earlier window with later filtered-speed acceleration; 100/200ms shifts are NOT inferred real delays')


def audit(batch_path):
    batch=json.loads(batch_path.read_text());paths=batch.get('attempts',[])
    if len(paths)!=5 or len(set(paths))!=5 or not batch.get('pass_'):raise ValueError('Complete distinct five-run batch required')
    if hashlib.sha256(ELF.read_bytes()).hexdigest()!=ELF_SHA:raise ValueError('Exact diagnostic ELF required')
    results=[]
    for path in paths:
        r=json.loads(Path(path).read_text())
        if r.get('image_sha256')!=BIN_SHA or r.get('elf_sha256')!=ELF_SHA:raise ValueError('Same exact image required')
        capture=identification.decode(Path(path),ELF)
        if not capture['board_acceptance_verified'] or not capture['closure_verified']:
            raise ValueError('Protection/closure evidence absent')
        if capture!=r['ka_capture']:raise ValueError('Saved vs re-decoded current/velocity windows mismatch')
        results.append(dict(receipt=path,**analyze(capture['windows'])))
    return dict(offline_only=True,hardware_access=False,parameter_writes=False,runs=results,
        verified_software_mismatch='Velocity: variable-dt first-order LPF tau=20ms. Iq: latest FOC value sampled by speed task, no matching LPF. Current ADC timestamp not saved.',
        reconstruction_limit='Only block means and filtered-speed endpoints survive. Original raw encoder steps, speed instants, 1kHz Iq samples and exact current ages are unavailable.',
        direction_conclusion='Measured Iq and mechanical speed are positive in every scored window; no evidence for flipping a sign from these regressions.',
        no_fixed_lag_positive_in_all_five=not any(all(
            r['lag_sensitivity'][j]['ka'] is not None and r['lag_sensitivity'][j]['ka']>0
            for r in results) for j in range(len(LAGS))),
        approximate_lpf_positive_runs=sum(r['approximate_current_lpf_20ms']['ka']>0 for r in results),
        final='Known measurement-chain mismatch; existing data cannot identify its exact contribution or justify new Ka, polarity flip, or a chosen delay.')


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--batch',required=True,type=Path);a=p.parse_args(argv)
    print(json.dumps(audit(a.batch),indent=2,allow_nan=False));return 0


if __name__=='__main__':raise SystemExit(main())
