"""Offline DQA1/legacy dq evidence checks. No serial, debugger, reset or writes.

Old alternating STATUS/VOLTAGE replies are never treated as a coherent frame.
Full-rate maxima require the new saved SRAM stats and its matching ELF.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import re
import statistics
import struct

LD=20.03e-6
LQ=11.18e-6


def fields(text):
    # Real ARM Pigweed metadata is attached without a whitespace separator
    # after the last argument. Do not parse module/file as part of a float.
    if '\u25a0msg\u2666' in text:
        text=text.split('\u25a0msg\u2666',1)[1].split('\u25a0',1)[0]
    return dict(re.findall(r'([A-Za-z0-9_]+)=([^\s]+)',text))


def coherent_frames(receipt):
    joined={}
    for entry in receipt.get('tokenized_decoded',[]):
        line=entry.get('decoded','')
        m=re.search(r'\bDQA ([RSIV]) ',line)
        if not m:continue
        f=fields(line)
        if 'seq' not in f:continue
        seq=int(f['seq']);row=joined.setdefault(seq,{'parts':set(),'part_values':{}})
        if m[1] in row['parts']:
            if row['part_values'][m[1]]!=f:
                raise ValueError('Conflicting DQA sequence: reset/mixed capture')
            continue
        row['parts'].add(m[1])
        row['part_values'][m[1]]=f
        for k,v in f.items():row[k]=int(v) if k in ('seq','us','flags','elapsed_us') else float(v)
    complete=[{k:v for k,v in r.items() if k not in ('parts','part_values')}
              for r in joined.values() if r['parts']==set('RSIV')]
    return sorted(complete,key=lambda r:r['seq']),len(joined)-len(complete)


def frame_checks(frames):
    result=dict(coherent_frames=len(frames),configured_math_bad=0,nominal_sign_bad=0,
                unit_chain_error_max_rad_s=None,off_nonzero=0,limit_vector_max_v=None)
    if not frames:return result
    errors=[];magnitudes=[]
    for f in frames:
        values=[f[k] for k in ('we_rad_s','mech_rpm','id','iq','vd_dec','vq_dec','vd_cmd','vq_cmd')]
        if not all(math.isfinite(x) for x in values):raise ValueError('Nonfinite coherent DQA frame')
        on=bool(f['flags']&1);mode=(f['flags']>>8)&3
        nominal=(-f['we_rad_s']*LQ*f['iq'],f['we_rad_s']*LD*f['id'])
        actual=(f['vd_dec'],f['vq_dec'])
        expected=tuple(v*(-1 if mode&(1<<k) else 1) if on else 0. for k,v in enumerate(nominal))
        if any(abs(a-b)>1e-7 for a,b in zip(actual,expected)):result['configured_math_bad']+=1
        if on and any(a*b<0 for a,b in zip(actual,nominal)):result['nominal_sign_bad']+=1
        if not on and any(x!=0 for x in actual):result['off_nonzero']+=1
        errors.append(abs(f['we_rad_s']-f['mech_rpm']*10*2*math.pi/60))
        magnitudes.append(math.hypot(f['vd_cmd'],f['vq_cmd']))
    result['unit_chain_error_max_rad_s']=max(errors)
    result['limit_vector_max_v']=max(magnitudes)
    return result


def saved_stats(receipt,elf):
    if elf is None:return None
    from foc_path_profile_report import symbols
    elf=Path(elf);ram_path=Path(receipt['ram_capture'])
    if hashlib.sha256(elf.read_bytes()).hexdigest()!=receipt.get('elf_sha256'):
        raise ValueError('Matching receipt ELF required for SRAM interpretation')
    ram=ram_path.read_bytes()
    if len(ram)!=0x20000:raise ValueError('Complete SRAM capture required')
    if receipt.get('ram_sha256') and hashlib.sha256(ram).hexdigest()!=receipt['ram_sha256']:
        raise ValueError('Saved SRAM hash mismatch')
    # Do not interpret a previous firmware's same-sized RAM as this image.
    flash=Path(receipt['flash_capture']).read_bytes()
    vtor=receipt['vtor'];vtor=int(vtor,0) if isinstance(vtor,str) else vtor
    image=elf.with_suffix('.bin').read_bytes()
    if vtor!=0x08008000 or len(flash)!=512*1024 or flash[vtor-0x08000000:vtor-0x08000000+len(image)]!=image:
        raise ValueError('Complete same-capture Flash/VTOR does not match candidate A')
    addr,size=symbols(elf)['dq_audit']
    if size!=148 or not 0<=addr-0x20000000<=len(ram)-size:raise ValueError('DQA1 SRAM ABI/bounds')
    names=('samples run_n zero_n start_n cruise_n sat_n first_sat_us nominal_d_bad '
           'nominal_q_bad config_bad invalid_n started start_us zero_d_max zero_q_max '
           'start_d_max start_q_max cruise_d_sum cruise_q_sum we_abs_max we_chain_error_max').split()
    s=dict(zip(names,struct.unpack_from('<13I8f',ram,addr-0x20000000+64)))
    if s['sat_n']==0:s['first_sat_us']=None
    s['cruise_d_mean']=s['cruise_d_sum']/s['cruise_n'] if s['cruise_n'] else None
    s['cruise_q_mean']=s['cruise_q_sum']/s['cruise_n'] if s['cruise_n'] else None
    s['coverage']='all accepted normal PI frames; excludes discriminator hold/reject'
    return s


def evidence(receipt,elf=None):
    frames,missing=coherent_frames(receipt)
    checks=frame_checks(frames)
    result=dict(frame_checks=checks,incomplete_log_frames=missing,
                full_rate=saved_stats(receipt,elf),voltage_source=None,
                stationary_abs_peak_v=None,startup_500ms_abs_peak_v=None,
                cruise_mean_dec_v=None,voltage_first_saturation_us=None,
                vq_cmd_observed_mean_v=None)
    full=result['full_rate']
    if full:
        result['stationary_abs_peak_v']=[full['zero_d_max'],full['zero_q_max']] if full['zero_n'] else None
        result['startup_500ms_abs_peak_v']=[full['start_d_max'],full['start_q_max']] if full['start_n'] else None
        result['cruise_mean_dec_v']=[full['cruise_d_mean'],full['cruise_q_mean']]
        result['voltage_first_saturation_us']=full['first_sat_us']
    if frames:
        running=[f for f in frames if f['flags']&2]
        if running:
            result['vq_cmd_observed_mean_v']=statistics.mean(f['vq_cmd'] for f in running)
            result['voltage_source']='coherent 100ms task log snapshots; not full-rate mean'
    else:
        volts=[x['values'] for x in receipt.get('dq_samples',[])
               if x['command'].endswith('VOLTAGE') and x['values'].get('VALID')=='1']
        result['legacy_voltage_samples']=len(volts)
        status=[x['values'] for x in receipt.get('dq_samples',[]) if x['command'].endswith('STATUS')
                and x['values'].get('VALID')=='1' and 'OMEGA_E_MRAD_S' in x['values']]
        result['legacy_observed_we_abs_max_rad_s']=max(abs(int(x['OMEGA_E_MRAD_S']))*.001 for x in status) if status else None
        if volts:
            result['vq_cmd_observed_mean_v']=statistics.mean(int(v['VQ_UV'])*1e-6 for v in volts)
            result['voltage_source']='legacy alternating queries; no same-frame we/Id/Iq'
            result['legacy_observed_saturation_count']=sum(v.get('SAT')=='1' for v in volts)
            result['legacy_dec_range_v']={axis:[min(int(v[key])*1e-6 for v in volts),
                max(int(v[key])*1e-6 for v in volts)] for axis,key in (('d','VD_FF_UV'),('q','VQ_FF_UV'))}
        result['missing_full_rate_reason']='No DQA1 SRAM stats: stationary/startup peaks and earlier voltage saturation are unproven'
    return result


def compare(off,on,off_elf=None,on_elf=None):
    a=evidence(off,off_elf);b=evidence(on,on_elf)
    av=a['vq_cmd_observed_mean_v'];bv=b['vq_cmd_observed_mean_v']
    earlier=None
    if a['full_rate'] and b['full_rate']:
        ta=a['voltage_first_saturation_us'];tb=b['voltage_first_saturation_us']
        earlier=(tb is not None and (ta is None or tb<ta))
    return dict(offline_only=True,board_actions=0,model=dict(pole_pairs=10,Ld_H=LD,Lq_H=LQ),off=a,on=b,
        on_minus_off_observed_mean_vq_v=bv-av if bv is not None and av is not None else None,
        on_voltage_saturates_earlier=earlier,
        warning='Independent runs/phase coverage differ. Difference in Vq includes PI response, not just decoupling. Iq SAT_MS is not voltage saturation.')


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--off',type=Path,required=True);p.add_argument('--on',type=Path,required=True)
    p.add_argument('--off-elf',type=Path);p.add_argument('--on-elf',type=Path)
    a=p.parse_args()
    print(json.dumps(compare(json.loads(a.off.read_text()),json.loads(a.on.read_text()),
                            a.off_elf,a.on_elf),indent=2,allow_nan=False))


if __name__=='__main__':main()
