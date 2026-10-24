"""Files-only mechanical model fit. No device access or parameter write.

Iq_lp20 = (J/Kt)*actual_alpha + (B/Kt)*omega + (Tc/Kt)*sign(omega) + bias.
Absolute J/B require independently calibrated Kt in Nm / dq-A, not a tuned BEMF gain.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import re
import statistics
import struct

CAPACITY=128
POINT_SIZE=36
SIZE=4712
MIN_SPEED_RAD_S=20*math.pi/30
MAX_MEAN_ABS_ID_A=.05 # analysis admission, never a protection threshold
META=('generation count observations flags first_encoder_us last_encoder_us '
      'first_seq last_seq read_failures publish_cycles_max first_omega active '
      'bin_start_us last_observe_us last_adc_seq bin_samples bin_flags raw_sum '
      'duration_s iq_lpf prev_iq iq_integral matched_integral id_abs_integral '
      'omega_integral prev_omega').split()


def decode_bytes(data,session='capture'):
    if len(data)!=SIZE:raise ValueError('Mechanical ABI mismatch')
    m=dict(zip(META,struct.unpack_from('<10If6Ii8f',data,CAPACITY*POINT_SIZE)))
    if m['count']>CAPACITY:raise ValueError('Invalid point count')
    rows=[];start=m['first_encoder_us'];omega=m['first_omega'];seq=m['first_seq']
    for i in range(m['count']):
        end,adc,dt,n,delta,flags,w,wm,iq,matched,ida=struct.unpack_from('<IIHHhH5f',data,i*POINT_SIZE)
        if ((end-start)&0xffffffff)!=dt or not 0<((adc-seq)&0xffffffff)<0x80000000:
            raise ValueError('Timestamp/ADC sequence reconstruction mismatch')
        row=dict(session=session,index=i+1,start_us=start,end_us=end,dt_s=dt*1e-6,
            omega_start_rad_s=omega,omega_end_rad_s=w,omega_mean_rad_s=wm,
            iq_mean_a=iq,iq_matched_mean_a=matched,id_abs_mean_a=ida,
            mechanical_delta_rad=delta*2*math.pi/16384,flags=flags,samples=n,adc_seq=adc)
        rows.append(row);start=end;omega=w;seq=adc
    if rows and (start!=m['last_encoder_us'] or seq!=m['last_seq']):raise ValueError('Capture endpoint mismatch')
    return dict(meta=m,rows=rows,span_s=((start-m['first_encoder_us'])&0xffffffff)*1e-6,
        frozen_at_capacity=m['count']==CAPACITY,
        timestamp_semantics='Current: coherent accepted ADC software pair-read; encoder: SPI receive, not analog aperture. All ~1kHz observations integrated into ~64ms bins, not all 20kHz ADC pairs.')


def decode(receipt,elf):
    from foc_path_profile_report import symbols
    r=json.loads(receipt.read_text());ram=Path(r['ram_capture']).read_bytes()
    flash=Path(r['final_capture']).read_bytes();binary=elf.with_suffix('.bin').read_bytes()
    if (len(ram)!=0x20000 or hashlib.sha256(ram).hexdigest()!=r['ram_sha256'] or
        hashlib.sha256(flash).hexdigest()!=r['final_sha256'] or
        hashlib.sha256(elf.read_bytes()).hexdigest()!=r['elf_sha256'] or
        hashlib.sha256(binary).hexdigest()!=r['image_sha256'] or
        flash[0x8000:0x8000+len(binary)]!=binary):raise ValueError('Same-session ELF/BIN/Flash/RAM required')
    address,size=symbols(elf)['mechanical_capture'];offset=address-0x20000000
    if size!=SIZE or not 0<=offset<=len(ram)-SIZE:raise ValueError('Mechanical RAM bounds')
    result=decode_bytes(ram[offset:offset+SIZE],str(receipt))
    result['session_hash']=r['ram_sha256']
    result['board_verified']=board_acceptance(r)
    return result


def board_acceptance(r):
    snapshot=r.get('snapshot',{});timing=snapshot.get('timing',{})
    first=snapshot.get('first_fault',{});terminal=r.get('terminal_status',{})
    expected_timeout=(first.get('valid')==1 and first.get('domain')==3 and
        first.get('fault_reason')==3 and first.get('timeout_reason')==0 and
        first.get('protection_flags')==0 and terminal.get('OUTCOME')=='RUNDOWN_TIMEOUT')
    encoder=r.get('encoder_saved',{});outputs=r.get('outputs',{})
    fault=r.get('postflight',{}).get('MOTOR TEST FAULT','')
    return bool(r.get('preflight_pass') and r.get('final_outputs_off') and
        r.get('final_cpu_halted') and r.get('all_app_private_unchanged') and
        outputs.get('VTOR')==0x08008000 and not outputs.get('SD',64)&64 and
        not outputs.get('BDTR',0xc000)&0xc000 and outputs.get('CCER')==0 and
        r.get('start_attempts')==1 and
        timing.get('deadline_miss')==0 and timing.get('actual_late_count')==0 and
        0<timing.get('wall_max_us',0)<50 and timing.get('actual_margin_min_us',0)>1 and
        snapshot.get('cur_confirm',{}).get('fault')==0 and
        (first.get('valid')==0 or expected_timeout) and terminal.get('FLT')=='0' and
        re.search(r'(?:^|\s)VALID=0(?:\s|$)',fault) and re.search(r'(?:^|\s)FLAGS=0(?:\s|$)',fault) and
        encoder.get('first_fault',{}).get('valid')==0 and
        all(encoder.get('counters',{}).get(k)==0 for k in
            ('timeouts','dma_errors','schedule_misses','control_stale')))


def windows(rows,group):
    accepted=[];rejected=[]
    sessions=dict.fromkeys(r['session'] for r in rows)
    for session in sessions:
        source=[r for r in rows if r['session']==session]
        for i in range(0,len(source)-group+1,group):
            part=source[i:i+group];reasons=[]
            if any(r['flags'] for r in part):reasons.append('QUALITY_FLAGS')
            if any(r['flags'] for r in source[max(0,i-2):i]):reasons.append('POST_INVALID_FILTER_SETTLING')
            if any(not .063<=r['dt_s']<=.066 for r in part):reasons.append('INTERVAL')
            finite=all(math.isfinite(r[k]) for r in part for k in (
                'dt_s','omega_start_rad_s','omega_end_rad_s','omega_mean_rad_s',
                'iq_matched_mean_a','id_abs_mean_a'))
            if not finite:reasons.append('NONFINITE')
            dt=sum(r['dt_s'] for r in part)
            if not finite or dt<=0:
                rejected.append(dict(session=session,index=part[0]['index'],reasons=reasons or ['INTERVAL']));continue
            w0=part[0]['omega_start_rad_s'];w1=part[-1]['omega_end_rad_s']
            if any(abs(r[k])<MIN_SPEED_RAD_S for r in part for k in ('omega_start_rad_s','omega_end_rad_s')):
                reasons.append('REST_OR_BREAKAWAY')
            signs={1 if r[k]>0 else -1 for r in part for k in ('omega_start_rad_s','omega_end_rad_s')}
            if len(signs)!=1:reasons.append('DIRECTION_CHANGE')
            if any(r['id_abs_mean_a']>MAX_MEAN_ABS_ID_A for r in part):reasons.append('ID_NOT_NEAR_ZERO')
            for left,right in zip(part,part[1:]):
                if left['end_us']!=right['start_us']:reasons.append('GAP')
            point=dict(session=session,index=part[0]['index'],dt_s=dt,
                alpha=(w1-w0)/dt,omega=sum(r['omega_mean_rad_s']*r['dt_s'] for r in part)/dt,
                iq=sum(r['iq_matched_mean_a']*r['dt_s'] for r in part)/dt,
                direction=1 if w1>0 else -1,reasons=sorted(set(reasons)))
            (rejected if reasons else accepted).append(point)
    return accepted,rejected


def solve(points):
    # RMS-scaled weighted four-column least squares. Rank/conditioning are
    # checked, never repaired by an arbitrary ridge or negative-J sign flip.
    x=[[r['alpha'],r['omega'],r['direction'],1.] for r in points]
    weight=[r['dt_s'] for r in points];sw=sum(weight)
    scale=[math.sqrt(sum(w*v[j]**2 for v,w in zip(x,weight))/sw) for j in range(4)]
    if any(s<1e-12 for s in scale):raise ValueError('RANK_DEFICIENT')
    z=[[v[j]/scale[j] for j in range(4)] for v in x]
    gram=[[sum(w*v[j]*v[k] for v,w in zip(z,weight))/sw for k in range(4)] for j in range(4)]
    rhs=[sum(w*v[j]*r['iq'] for v,w,r in zip(z,weight,points))/sw for j in range(4)]
    a=[gram[j][:]+[float(j==k) for k in range(4)]+[rhs[j]] for j in range(4)]
    for col in range(4):
        pivot=max(range(col,4),key=lambda j:abs(a[j][col]))
        if abs(a[pivot][col])<1e-9:raise ValueError('RANK_DEFICIENT')
        a[col],a[pivot]=a[pivot],a[col];d=a[col][col];a[col]=[v/d for v in a[col]]
        for row in range(4):
            if row!=col:
                q=a[row][col];a[row]=[v-q*u for v,u in zip(a[row],a[col])]
    condition=max(sum(abs(v) for v in row) for row in gram)*max(sum(abs(v) for v in row[4:8]) for row in a)
    coeff=[a[j][8]/scale[j] for j in range(4)]
    residual=[r['iq']-sum(c*v for c,v in zip(coeff,row)) for r,row in zip(points,x)]
    mean=sum(w*r['iq'] for w,r in zip(weight,points))/sw
    sse=sum(w*e*e for w,e in zip(weight,residual));sst=sum(w*(r['iq']-mean)**2 for w,r in zip(weight,points))
    return dict(j_over_kt=coeff[0],b_over_kt=coeff[1],coulomb_over_kt=coeff[2],bias_a=coeff[3],
        condition_inf_scaled=condition,r2=1-sse/sst if sst>1e-20 else 0,
        residual_rms_a=math.sqrt(sse/sw),residuals_a=residual)


def fit(rows,group=1):
    points,rejected=windows(rows,group)
    out=dict(accepted=points,rejected=rejected,n=len(points),group=group,problems=[],qualified=False)
    if len(points)<40:out['problems'].append('INSUFFICIENT_WINDOWS');return out
    if {r['direction'] for r in points}!={-1,1}:out['problems'].append('BOTH_DIRECTIONS_REQUIRED')
    if statistics.pstdev(r['alpha'] for r in points)<5:out['problems'].append('INSUFFICIENT_ACCELERATION_EXCITATION')
    if statistics.pstdev(r['omega'] for r in points)<2:out['problems'].append('INSUFFICIENT_SPEED_EXCITATION')
    try:out.update(solve(points))
    except ValueError as error:out['problems'].append(str(error));return out
    if out['j_over_kt']<=0 or out['b_over_kt']<0 or out['coulomb_over_kt']<0:out['problems'].append('NONPHYSICAL_COEFFICIENT')
    if out['condition_inf_scaled']>1e5:out['problems'].append('ILL_CONDITIONED')
    if out['r2']<.7 or out['residual_rms_a']>.03:out['problems'].append('POOR_MODEL_FIT')
    out['qualified']=not out['problems'];return out


def report(captures,kt=None,kt_calibrated=False,kt_source=''):
    if kt is not None and (not math.isfinite(kt) or kt<=0):raise ValueError('Positive finite dq torque constant required')
    if kt_calibrated and (kt is None or not kt_source.strip()):raise ValueError('Calibrated Kt requires a value and source')
    rows=[r for capture in captures for r in capture['rows']]
    primary=fit(rows);sensitivity=fit(rows,2)
    issues=list(primary['problems'])
    if not captures or not all(c.get('board_verified') for c in captures):issues.append('BOARD_ACCEPTANCE_NOT_VERIFIED')
    if not sensitivity['qualified']:issues.append('DOUBLE_WINDOW_FIT_FAILED')
    elif primary.get('j_over_kt',0)>0:
        if abs(sensitivity['j_over_kt']/primary['j_over_kt']-1)>.3:issues.append('WINDOW_SENSITIVE')
    sessions=list(dict.fromkeys(r['session'] for r in rows));heldout=[]
    if len(sessions)<3:issues.append('INDEPENDENT_SESSIONS_REQUIRED')
    else:
        for session in sessions:
            train=fit([r for r in rows if r['session']!=session])
            test=[r for r in primary['accepted'] if r['session']==session]
            valid=bool(train['qualified'] and test)
            rms=None
            if valid:
                c=[train[k] for k in ('j_over_kt','b_over_kt','coulomb_over_kt','bias_a')]
                errors=[r['iq']-sum(v*x for v,x in zip(c,(r['alpha'],r['omega'],r['direction'],1))) for r in test]
                rms=math.sqrt(sum(e*e for e in errors)/len(errors))
                valid=rms<=.03 and primary.get('j_over_kt',0)>0 and abs(train['j_over_kt']/primary['j_over_kt']-1)<=.3
            heldout.append(dict(session=session,passed=valid,residual_rms_a=rms))
        if not all(r['passed'] for r in heldout):issues.append('SESSION_SENSITIVITY')
    qualified=not issues
    absolute=None
    if qualified and kt_calibrated:
        absolute=dict(kt_nm_per_dq_a=kt,kt_source=kt_source,
            J_kg_m2=primary['j_over_kt']*kt,B_nm_s_per_rad=primary['b_over_kt']*kt,
            coulomb_nm=primary['coulomb_over_kt']*kt)
    candidate={k:primary.get(k) for k in ('j_over_kt','b_over_kt','coulomb_over_kt','bias_a')}
    return dict(primary=primary,sensitivity=sensitivity,heldout=heldout,problems=sorted(set(issues)),
        normalized_candidate=candidate,normalized_qualified=qualified,absolute_parameters=absolute,
        kt_independently_identified=False,kt_calibrated=kt_calibrated,
        parameter_writes=False,dob_control_enabled=False,dob_shadow_ready=qualified,
        formula='Iq_lp20 = J/Kt * delta(omega_filtered)/dt + B/Kt * mean(omega_filtered) + Tc/Kt * sign(omega) + bias',
        units=dict(omega='mechanical rad/s',alpha='mechanical rad/s^2',j_over_kt='A*s^2/rad',b_over_kt='A*s/rad'),
        qualification='Only normalized coefficients are identifiable from Iq and speed. No residual cherry-picking, sign flip, fitted time shift, invented Kt, automatic PI write or DOB actuation.')


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--receipts',type=Path,nargs='+',required=True);p.add_argument('--elf',type=Path,required=True)
    p.add_argument('--kt-nm-per-dq-a',type=float);p.add_argument('--kt-calibrated',action='store_true')
    p.add_argument('--kt-source',default='');a=p.parse_args(argv)
    if len(set(x.resolve() for x in a.receipts))!=len(a.receipts):p.error('Duplicate receipts are not independent repeats')
    captures=[decode(r,a.elf) for r in a.receipts]
    if len({c['session_hash'] for c in captures})!=len(captures):p.error('Repeated RAM captures are not independent sessions')
    print(json.dumps(report(captures,a.kt_nm_per_dq_a,a.kt_calibrated,a.kt_source),indent=2,allow_nan=False))


if __name__=='__main__':main()
