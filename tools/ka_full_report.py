"""FILES ONLY: complete acceleration capture and matched-filter Ka candidate fit."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import statistics
import struct

CAPACITY=240
SIZE=5872
META=('generation count observations begin_us first_encoder_us last_encoder_us '
      'first_adc_seq last_adc_seq read_failures flags active publish_cycles_max '
      'first_speed first_ref net_lpf prev_iq bin_start_us bin_seq last_observe_us '
      'last_observe_seq interval_samples interval_flags duration_s iq_integral '
      'friction_integral net_integral raw_sum first_raw reserved').split()


def decode_bytes(data):
    if len(data)!=SIZE:raise ValueError('Exact full-capture ABI required')
    m=dict(zip(META,struct.unpack_from('<12I4f6I4fiHH',data,5760)))
    if m['count']>CAPACITY:raise ValueError('Invalid count')
    frames=[];enc=m['first_encoder_us'];seq=m['first_adc_seq'];raw=m['first_raw']
    speed=m['first_speed'];reference=m['first_ref'];travel=0
    for i in range(m['count']):
        dt,age,relative,step,delta,iq,fric,net,v,ref,acc,n,flags=struct.unpack_from('<HHhH7hBB',data,i*24)
        start=enc;enc=(enc+dt)&0xffffffff;seq=(seq+step)&0xffffffff
        raw=(raw+delta)&16383;travel-=delta*360/16384
        end_speed=v*.01;end_ref=ref*.01
        frames.append(dict(seq=i+1,start_us=start,end_us=enc,duration_s=dt*1e-6,
            relative_end_us=(enc-m['first_encoder_us'])&0xffffffff,
            current_source_us=(enc+relative)&0xffffffff,current_minus_encoder_us=relative,
            current_age_at_task_us=age-relative,task_age_us=age,adc_seq=seq,
            samples=n,flags=flags,raw_delta=delta,encoder_raw=raw,travel_deg=travel,
            iq_mean_a=iq*.0001,friction_mean_a=fric*.0001,
            matched_net_iq_mean_a=net*.0001,speed_start_rpm=speed,speed_end_rpm=end_speed,
            ref_start_rpm=reference,ref_end_rpm=end_ref,accel_ref_end_rpm_s=acc*.1,
            actual_acceleration_rpm_s=(end_speed-speed)/(dt*1e-6) if dt else None))
        speed=end_speed;reference=end_ref
    if frames and (enc!=m['last_encoder_us'] or seq!=m['last_adc_seq']):
        raise ValueError('Full timestamp/ADC sequence reconstruction mismatch')
    complete=m['count']==CAPACITY
    ref_finished=bool(frames and abs(m['first_ref'])<.1 and abs(frames[-1]['ref_end_rpm']-240)<.1 and
        abs(frames[-1]['accel_ref_end_rpm_s'])<.1 and
        any(f['accel_ref_end_rpm_s']>10 for f in frames))
    rel=[f['current_minus_encoder_us'] for f in frames]
    return dict(meta=m,frames=frames,complete=complete,reference_acceleration_covered=ref_finished,
        all_observations_valid=not m['flags'],span_us=(enc-m['first_encoder_us'])&0xffffffff,
        current_minus_encoder_us=dict(min=min(rel),max=max(rel),mean=statistics.mean(rel)) if rel else None,
        publisher_max_us=m['publish_cycles_max']/170,
        ka_identified=None,parameter_writes=False,
        semantics='~1kHz task observations ALL integrated into consecutive ~10ms bins for 2.4s; current is coherent ADC software timestamp, encoder timestamp is SPI receive. Not the physical analog aperture and not all 20kHz ADC samples. Current/friction diagnostic net uses the same variable-dt 20ms LPF as speed, then time averaging; acceleration uses measured filtered speed endpoints, not accel_ref.')


def decode(receipt,elf):
    from foc_path_profile_report import symbols
    r=json.loads(receipt.read_text());ram=Path(r['ram_capture']).read_bytes()
    flash=Path(r['final_capture']).read_bytes();binary=elf.with_suffix('.bin').read_bytes()
    if (len(ram)!=0x20000 or hashlib.sha256(ram).hexdigest()!=r['ram_sha256'] or
        hashlib.sha256(flash).hexdigest()!=r['final_sha256'] or
        hashlib.sha256(elf.read_bytes()).hexdigest()!=r['elf_sha256'] or
        hashlib.sha256(binary).hexdigest()!=r['image_sha256'] or
        flash[0x8000:0x8000+len(binary)]!=binary):raise ValueError('Same-session BIN/ELF/Flash/RAM required')
    addr,size=symbols(elf)['ka_full_diagnostic'];offset=addr-0x20000000
    if size!=SIZE or not 0<=offset<=len(ram)-size:raise ValueError('Wrong full RAM symbol')
    out=decode_bytes(ram[offset:offset+size]);out['closure_verified']=bool(
        r.get('final_outputs_off') and r.get('final_cpu_halted') and r.get('all_app_private_unchanged'))
    result=r.get('result',{})
    out['board_acceptance_verified']=bool(r.get('preflight_pass') and
        result.get('acquisition_complete') and result.get('full_uart_telemetry_complete') and
        result.get('expected_process_timeout_snapshot') and
        result.get('deadline_miss')==0 and result.get('ccr_late')==0)
    return out


def bins(frames,group):
    out=[]
    for i in range(0,len(frames)-group+1,group):
        rows=frames[i:i+group];dt=sum(f['duration_s'] for f in rows)
        flags=0
        for f in rows:flags|=f['flags']
        out.append(dict(seq=len(out)+1,duration_s=dt,flags=flags,
            speed_start_rpm=rows[0]['speed_start_rpm'],speed_end_rpm=rows[-1]['speed_end_rpm'],
            mean_speed=.5*(rows[0]['speed_start_rpm']+rows[-1]['speed_end_rpm']),
            acceleration=(rows[-1]['speed_end_rpm']-rows[0]['speed_start_rpm'])/dt if dt>0 else 0,
            net_iq=sum(f['matched_net_iq_mean_a']*f['duration_s'] for f in rows)/dt if dt>0 else 0))
    return out


def fit(frames,group):
    accepted=[];rejected=[]
    for f in bins(frames,group):
        reasons=[]
        if f['flags']:reasons.append('OBSERVATION_FLAGS')
        if not .009*group<=f['duration_s']<=.012*group:reasons.append('INTERVAL')
        if min(f['speed_start_rpm'],f['speed_end_rpm'])<10:reasons.append('REST_OR_OTHER_DIRECTION')
        (rejected if reasons else accepted).append(dict(f,reasons=reasons))
    out=dict(bin_ms=10*group,n=len(accepted),accepted=accepted,rejected=rejected,
             trusted=False,ka_identified=None,problems=[])
    if len(accepted)<8:out['problems'].append('INSUFFICIENT_WINDOWS');return out
    x=[f['acceleration'] for f in accepted];y=[f['net_iq'] for f in accepted]
    w=[f['duration_s'] for f in accepted];sw=sum(w)
    mx=sum(a*c for a,c in zip(x,w))/sw;my=sum(a*c for a,c in zip(y,w))/sw
    xx=sum(c*(a-mx)**2 for a,c in zip(x,w));yy=sum(c*(a-my)**2 for a,c in zip(y,w))
    if xx/sw<400:out['problems'].append('INSUFFICIENT_ACCELERATION_EXCITATION');return out
    k=sum(c*(a-mx)*(b-my) for a,b,c in zip(x,y,w))/xx;b=my-k*mx
    residual=[v-k*a-b for a,v in zip(x,y)]
    sse=sum(c*r*r for c,r in zip(w,residual));r2=1-sse/yy if yy>1e-24 else 0
    leverage=[c/sw+c*(a-mx)**2/xx for a,c in zip(x,w)]
    speeds=[f['mean_speed'] for f in accepted];mean_speed=sum(a*c for a,c in zip(speeds,w))/sw
    vv=sum(c*(a-mean_speed)**2 for a,c in zip(speeds,w))
    corr=sum(c*(a-mean_speed)*r for a,r,c in zip(speeds,residual,w))/math.sqrt(vv*sse) if vv*sse>1e-24 else 0
    loo=[]
    for i in range(len(x)):
        rows=[(a,v,c) for j,(a,v,c) in enumerate(zip(x,y,w)) if j!=i]
        wt=sum(c for _,_,c in rows);ax=sum(a*c for a,_,c in rows)/wt;ay=sum(v*c for _,v,c in rows)/wt
        dx=sum(c*(a-ax)**2 for a,_,c in rows)
        if dx>1e-20:loo.append(sum(c*(a-ax)*(v-ay) for a,v,c in rows)/dx)
    out.update(ka_identified=k,b_a=b,r2=r2,residual_rms_a=math.sqrt(sse/sw),
        residual_speed_correlation=corr,max_leverage=max(leverage),
        leave_one_out_min=min(loo) if loo else None,leave_one_out_max=max(loo) if loo else None)
    if k<=0:out['problems'].append('NONPOSITIVE_PHYSICAL_SLOPE')
    if r2<.6:out['problems'].append('POOR_LINEAR_FIT')
    if abs(corr)>.5:out['problems'].append('RESIDUAL_DEPENDS_ON_SPEED')
    if max(leverage)>.5:out['problems'].append('SINGLE_WINDOW_DOMINATES')
    if k>0 and loo and (min(loo)<=0 or max(abs(a/k-1) for a in loo)>.5):out['problems'].append('UNSTABLE_LEAVE_ONE_OUT')
    out['trusted']=not out['problems'];return out


def report(capture):
    primary=fit(capture['frames'],5);sensitivity=fit(capture['frames'],10)
    k=primary['ka_identified'];other=sensitivity['ka_identified']
    if k is not None and other is not None and (not k or abs(other/k-1)>.3):
        primary['problems'].append('WINDOW_SENSITIVE');primary['trusted']=False
    if not capture['complete'] or not capture['reference_acceleration_covered']:
        primary['problems'].append('INCOMPLETE_ACCELERATION_COVERAGE');primary['trusted']=False
    if not (capture.get('closure_verified') and capture.get('board_acceptance_verified')):
        primary['problems'].append('BOARD_ACCEPTANCE_NOT_VERIFIED');primary['trusted']=False
    return dict(primary=primary,sensitivity_100ms=sensitivity,parameter_writes=False,
        candidate_ka=k if primary['trusted'] else None,
        formula='mean(LPF20ms(Iq_measured - Iq_friction_command)) = Ka * delta(filtered_measured_rpm)/delta(seconds) + b',
        units='A/(rpm/s)',qualification='Fixed complete ordered 50ms/100ms bins, no residual/t_stable cherry-picking, no fitted time shift/sign flip. b includes residual friction/load/bias. One closed-loop ramp can remain biased or insufficient; positive regression alone is not final calibration.',
        next_ab_multipliers=[.5,.75,1,1.25] if primary['trusted'] else [],
        final_ab_objective='whole acceleration-phase time-weighted abs(speed_ref-speed_meas), never t_stable')


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--receipt',type=Path,required=True)
    p.add_argument('--elf',type=Path,required=True);a=p.parse_args(argv)
    c=decode(a.receipt,a.elf);print(json.dumps(dict(capture=c,fit=report(c)),indent=2,allow_nan=False))

if __name__=='__main__':main()
