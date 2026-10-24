"""File-only acceleration audit and experiment-identity checks; no devices."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import re
import statistics
import struct
from foc_path_profile_report import symbols

FRAME_NAMES=('seq ms trajectory_update speed_ref speed_meas speed_error accel_ref '
    'iq_pi iq_acc_ff iq_fric iq_raw iq_cmd integrator trajectory_phase flags dt_s').split()
META_NAMES=('generation samples trace_count last_trace_ms trajectory_updates sign_errors zero_ff_errors '
    'formula_errors sync_errors pi_ff_opposed sat_samples aw_limited_samples unexpected_aw_samples '
    'enabled_samples first_sat_ms start_ms max_abs_accel max_abs_ff max_ff_limit_ratio '
    'saturation_s max_abs_integrator effective_ka').split()


def checks(frames,ka,limit=.5):
    problems=[]
    for f in frames:
        seq=f['seq'];expected=ka*f['accel_ref'] if f['flags']&1 else 0.
        if any(not math.isfinite(f[k]) for k in FRAME_NAMES[3:13]+['dt_s']):
            problems.append(dict(seq=seq,kind='NONFINITE'));continue
        for kind,error in (
            ('FORMULA',f['iq_acc_ff']-expected),
            ('ERROR_SIGN',f['speed_error']-(f['speed_ref']-f['speed_meas'])),
            ('TOTAL_SUM',f['iq_raw']-(f['iq_pi']+f['iq_acc_ff']+f['iq_fric'])),
            ('FINAL_CLAMP',f['iq_cmd']-max(-limit,min(limit,f['iq_raw'])))):
            if abs(error)>1e-5:problems.append(dict(seq=seq,kind=kind,error=error))
        if f['accel_ref']==0 and f['iq_acc_ff']!=0:problems.append(dict(seq=seq,kind='ZERO_ACCEL_NONZERO_FF'))
    for a,b in zip(frames,frames[1:]):
        if ((b['trajectory_update']-a['trajectory_update'])&0xffffffff)!=((b['seq']-a['seq'])&0xffffffff):
            problems.append(dict(seq=b['seq'],kind='TRAJECTORY_CYCLE_MISMATCH'))
    return dict(problems=problems,pi_ff_opposed_frames=sum(f['iq_pi']*f['iq_acc_ff']<0 for f in frames),
        opposed_is_automatic_fault=False,
        explanation='PI may oppose FF during braking/overspeed; that alone is not a sign bug. No PI-reduction claim without a matched acceleration-FF OFF run.')


def decode(receipt,elf):
    r=json.loads(receipt.read_text());ram=Path(r['ram_capture']).read_bytes();flash=Path(r['final_capture']).read_bytes()
    image=elf.with_suffix('.bin').read_bytes()
    if (len(ram)!=0x20000 or hashlib.sha256(ram).hexdigest()!=r.get('ram_sha256') or
        hashlib.sha256(flash).hexdigest()!=r['final_sha256'] or
        hashlib.sha256(elf.read_bytes()).hexdigest()!=r['elf_sha256'] or
        hashlib.sha256(image).hexdigest()!=r['image_sha256'] or flash[0x8000:0x8000+len(image)]!=image):
        raise ValueError('Exact same-image Flash/ELF/RAM evidence required')
    addr,size=symbols(elf)['speed_accel_audit'];offset=addr-0x20000000
    if size!=1112 or not 0<=offset<=len(ram)-size:raise ValueError('Audit ABI/bounds mismatch')
    meta=dict(zip(META_NAMES,struct.unpack_from('<16I6f',ram,offset+1024)))
    if meta['trace_count']>16:raise ValueError('Invalid audit publication count')
    frames=[dict(zip(FRAME_NAMES,struct.unpack_from('<3I10f2If',ram,offset+i*64))) for i in range(meta['trace_count'])]
    cmd=next(c['command'] for c in json.loads((elf.parent/'compile_commands.json').read_text())
        if c['file'].endswith('/Core/Src/main.c'))
    ka=meta['effective_ka']
    defines=sorted(x for x in re.findall(r'(?:^|\s)-D(\S+)',cmd)
        if not x.startswith('SPEED_ACCEL_FF_KA_A_PER_RPM_S='))
    same_control_key=hashlib.sha256('\n'.join(defines).encode()).hexdigest()
    return dict(feature='ACCEL_CURRENT_FF',offline_only=True,hardware_access=False,ka_a_per_rpm_s=ka,
        same_control_key_except_ka=same_control_key,
        bemf_runtime=r.get('bemf_switch',{}).get('ON'),meta=meta,frames=frames,checks=checks(frames,ka),
        resolution='100ms first 16 speed-control observations (~1.5s); maxima/counters cover every speed update, not a 20kHz ISR trace',
        note='Use the associated BEMF/FRIC readbacks and same recipe. No automatic motor-parameter or firmware writes.')


def history(path):
    b=json.loads(path.read_text());runs=[];max_a=max_ff=0.;matched=0
    for p in b['attempts']:
        r=json.loads(Path(p).read_text());aff=r['accel_ff_metrics'];fric=r['friction_metrics']['STATUS']
        runs.append(dict(receipt=p,bemf_enabled=r['bemf_enabled'],bemf_wire=r['bemf_switch']['ON'],
            accel_ff_on=aff['ON'],ka_na_per_rpm_s=aff['KA_NA_PER_RPM_S'],
            fric_on=fric['ON'],iq_saturation_ms=aff['SAT_MS']))
        # Join only same-seq R/C log messages, NOT nearby UART receive times.
        pairs={}
        for entry in r.get('tokenized_decoded',[]):
            line=entry['decoded'];m=re.search(r'FRC ([RC]) seq=(\d+)',line)
            if m:
                fields=dict(re.findall(r'(\w+)=(-?[0-9.]+)',line));pairs.setdefault(m[2],{})[m[1]]=fields
        for pair in pairs.values():
            if set(pair)=={'R','C'}:
                max_a=max(max_a,abs(float(pair['R']['accel_ref'])))
                max_ff=max(max_ff,abs(float(pair['C']['iq_acc_ff'])));matched+=1
    return dict(feature_actually_switched='BEMF_VOLTAGE_FF',runs=runs,
        acceleration_on_off_comparison=False,all_accel_ff_on=all(r['accel_ff_on']==1 for r in runs),
        observed_log_max_abs_accel_rpm_s=max_a,observed_log_max_abs_acc_ff_a=max_ff,
        same_seq_log_pairs=matched,log_peaks_are_not_full_rate=True,
        conclusion='These six runs cannot attribute the performance difference to switching acceleration FF; it stayed ON at the same Ka.')


def compare(off,on):
    if off.get('bemf_runtime')!=on.get('bemf_runtime') or off.get('bemf_runtime')!='0':
        raise ValueError('Matched, explicitly OFF BEMF required to isolate acceleration FF')
    if off['meta']['max_abs_ff']!=0:raise ValueError('Reference is not a zero-acceleration-FF baseline')
    if (not off.get('same_control_key_except_ka') or
        off['same_control_key_except_ka']!=on.get('same_control_key_except_ka')):
        raise ValueError('Non-Ka build definitions must match')
    for r in (off,on):
        if r['checks']['problems']:raise ValueError('Invalid formula/timing evidence')
        if not r['frames'] or not r['meta']['samples']:raise ValueError('Empty audit is not a baseline')
    def mean(r,k):return statistics.mean(f[k] for f in r['frames']) if r['frames'] else None
    def first_half(r):
        first=r['frames'][0]['ms'];f=[x for x in r['frames'] if ((x['ms']-first)&0xffffffff)<=500]
        return dict(frames=len(f),mean_abs_pi=statistics.mean(abs(x['iq_pi']) for x in f),
            mean_abs_error=statistics.mean(abs(x['speed_error']) for x in f),
            opposed_frames=sum(x['iq_pi']*x['iq_acc_ff']<0 for x in f))
    return dict(offline_only=True,pi_mean_off=mean(off,'iq_pi'),pi_mean_on=mean(on,'iq_pi'),
        first_500ms_off=first_half(off),first_500ms_on=first_half(on),
        integrator_peak_off=off['meta']['max_abs_integrator'],integrator_peak_on=on['meta']['max_abs_integrator'],
        saturation_s_off=off['meta']['saturation_s'],saturation_s_on=on['meta']['saturation_s'],
        first_sat_ms_off=None if off['meta']['first_sat_ms']==0xffffffff else off['meta']['first_sat_ms'],
        first_sat_ms_on=None if on['meta']['first_sat_ms']==0xffffffff else on['meta']['first_sat_ms'],
        qualification='First-window diagnostic comparison only; use full firmware metrics for phase MAE and repeat matched runs. PI need not decrease at every instant.')


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--history-batch',type=Path)
    p.add_argument('--receipt',type=Path);p.add_argument('--elf',type=Path)
    p.add_argument('--compare',nargs=2,type=Path);a=p.parse_args()
    if a.history_batch:r=history(a.history_batch)
    elif a.compare:r=compare(*(json.loads(x.read_text()) for x in a.compare))
    elif a.receipt and a.elf:r=decode(a.receipt,a.elf)
    else:p.error('Use --history-batch, --receipt/--elf, or --compare OFF.json ON.json')
    print(json.dumps(r,indent=2,allow_nan=False));return 0


if __name__=='__main__':raise SystemExit(main())
