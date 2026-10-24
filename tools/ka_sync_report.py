"""FILES ONLY: decode the frozen ~64ms Ka time-alignment diagnostic, never set Ka."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import statistics
import struct

FIELDS=('encoder_dt_us task_age_us current_relative_us adc_seq_step flags raw_delta '
        'iq_0p1ma speed_0p01rpm friction_0p1ma iq_minus_friction_lpf_0p1ma').split()
META=('generation count begin_us first_encoder_us first_adc_seq last_encoder_us last_adc_seq '
      'observations read_failures flags active publish_cycles_max first_raw_before reserved '
      'net_iq_lpf first_net_iq_lpf_before').split()


def decode_bytes(data,clock_hz=170000000):
    if len(data)!=1212:raise ValueError('Sync ABI must be 1212 bytes, not the old 100ms window ABI')
    meta=dict(zip(META,struct.unpack_from('<12I2H2f',data,1152)))
    if meta['count']>64:raise ValueError('Invalid publication count')
    points=[];enc=meta['first_encoder_us'];adc_seq=meta['first_adc_seq'];raw=meta['first_raw_before']
    counts=0;filtered_previous=None;problems=[]
    if meta['count']!=64:problems.append(dict(kind='INCOMPLETE_SHORT_WINDOW'))
    for i in range(meta['count']):
        p=dict(zip(FIELDS,struct.unpack_from('<HHhBB5h',data,i*18)))
        if i:enc=(enc+p['encoder_dt_us'])&0xffffffff;adc_seq=(adc_seq+p['adc_seq_step'])&0xffffffff
        raw=(raw+p['raw_delta'])&16383;counts-=p['raw_delta'] # Existing encoder direction=-1.
        iq=p['iq_0p1ma']*.0001;fric=p['friction_0p1ma']*.0001;speed=p['speed_0p01rpm']*.01
        dt=p['encoder_dt_us']*1e-6
        if p['flags'] or dt<=0:problems.append(dict(seq=i+1,flags=p['flags'],kind='OBSERVATION_QUALITY'))
        p.update(seq=i+1,encoder_us=enc,current_source_us=(enc+p['current_relative_us'])&0xffffffff,
            current_adc_seq=adc_seq,task_us=(enc+p['task_age_us'])&0xffffffff,
            current_age_at_task_us=p['task_age_us']-p['current_relative_us'],encoder_raw=raw,
            mechanical_counts=counts,mechanical_travel_deg=counts*360/16384,
            mechanical_speed_instant_rpm=-p['raw_delta']*60/(16384*dt) if dt>0 else None,
            mechanical_speed_filtered_rpm=speed,iq_measured_a=iq,iq_friction_a=fric,
            iq_minus_friction_lpf_a=p['iq_minus_friction_lpf_0p1ma']*.0001,
            filtered_acceleration_rpm_s=(speed-filtered_previous)/dt if filtered_previous is not None and dt>0 else None)
        filtered_previous=speed;points.append(p)
        if p['current_age_at_task_us']<0 or p['current_age_at_task_us']>200:
            problems.append(dict(seq=i+1,kind='CURRENT_TIME_NOT_AT_OR_BEFORE_TASK'))
    if points and (points[-1]['encoder_us']!=meta['last_encoder_us'] or points[-1]['current_adc_seq']!=meta['last_adc_seq']):
        raise ValueError('Timestamp/sequence reconstruction mismatch: likely range overflow or torn record')
    # Replay the *same task-snapshot* diagnostic LPF. Quantization uncertainty
    # is <=0.05mA per current/friction field; compare with bounded tolerance.
    state=meta['first_net_iq_lpf_before'];max_error=0.
    for p in points:
        dt=p['encoder_dt_us']*1e-6
        if p['flags']&1 or dt<=0 or dt>.002:continue
        state+=dt/(.020+dt)*((p['iq_measured_a']-p['iq_friction_a'])-state)
        max_error=max(max_error,abs(state-p['iq_minus_friction_lpf_a']))
    if max_error>.00016:problems.append(dict(kind='MATCHED_FILTER_REPLAY_MISMATCH',error_a=max_error))
    # Align measured current timestamps to encoder timestamps by interpolation.
    # Never shift by a fitted "best" lag or extrapolate at either boundary.
    cur_t=[((p['current_source_us']-meta['first_encoder_us']+0x80000000)&0xffffffff)-0x80000000 for p in points]
    monotonic=all(a<b for a,b in zip(cur_t,cur_t[1:]))
    if not monotonic and len(points)>1:problems.append(dict(kind='NONMONOTONIC_CURRENT_SOURCE'))
    j=0
    for p in points:
        t=(p['encoder_us']-meta['first_encoder_us'])&0xffffffff
        p['iq_interpolated_at_encoder_a']=None
        if not monotonic:continue
        while j+1<len(cur_t) and cur_t[j+1]<t:j+=1
        if j+1<len(cur_t) and cur_t[j]<=t<=cur_t[j+1] and cur_t[j+1]-cur_t[j]<=2000:
            a,b=points[j:j+2];f=(t-cur_t[j])/(cur_t[j+1]-cur_t[j])
            if not (a['flags']|b['flags']):
                p['iq_interpolated_at_encoder_a']=a['iq_measured_a']+f*(b['iq_measured_a']-a['iq_measured_a'])
    deltas=[p['current_relative_us'] for p in points]
    return dict(offline_only=True,hardware_access=False,parameter_writes=False,meta=meta,points=points,problems=problems,
        complete_short_window=meta['count']==64,all_observations_valid=not problems,
        span_us=(meta['last_encoder_us']-meta['first_encoder_us'])&0xffffffff if points else 0,
        current_minus_encoder_time_us=dict(min=min(deltas),max=max(deltas),mean=statistics.mean(deltas)) if deltas else None,
        publisher_max_cycles=meta['publish_cycles_max'],publisher_max_us=meta['publish_cycles_max']/clock_hz*1e6,
        matched_filter_replay_max_error_a=max_error,ka_identified=None,
        quantization='Iq/friction/diagnostic LPF 0.1mA, filtered speed .01rpm; exact integer source/encoder timestamp deltas except flagged overflow',
        timing_semantics='Encoder SPI receive timestamp; current existing ADC-pair software-read timestamp. Neither is a measured analog aperture. Current interpolation uses ~1kHz task snapshots, not all 20kHz ADC samples.',
        limitation='64 consecutive ~1ms points only. Alignment/shape evidence, NOT a full startup or reliable inertia identification. No automatic gain/sign/delay selection.')


def decode(receipt,elf):
    from foc_path_profile_report import symbols
    r=json.loads(receipt.read_text());ram=Path(r['ram_capture']).read_bytes()
    flash=Path(r['final_capture']).read_bytes();binary=elf.with_suffix('.bin').read_bytes()
    if (len(ram)!=0x20000 or hashlib.sha256(ram).hexdigest()!=r['ram_sha256'] or
        hashlib.sha256(flash).hexdigest()!=r['final_sha256'] or
        hashlib.sha256(elf.read_bytes()).hexdigest()!=r['elf_sha256'] or
        hashlib.sha256(binary).hexdigest()!=r['image_sha256'] or flash[0x8000:0x8000+len(binary)]!=binary):
        raise ValueError('Exact same-session Flash/RAM/BIN/ELF required')
    address,size=symbols(elf)['ka_sync_diagnostic'];offset=address-0x20000000
    if size!=1212 or not 0<=offset<=len(ram)-size:raise ValueError('Wrong sync RAM symbol/bounds')
    result=decode_bytes(ram[offset:offset+size])
    result['outputs_off_and_halted_verified']=bool(r.get('final_cpu_halted') and r.get('final_outputs_off'))
    return result


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--receipt',required=True,type=Path)
    p.add_argument('--elf',required=True,type=Path);a=p.parse_args(argv)
    print(json.dumps(decode(a.receipt,a.elf),indent=2,allow_nan=False));return 0


if __name__=='__main__':raise SystemExit(main())
