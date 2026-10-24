"""File-only current-loop A/B metrics; never accesses a device or changes PI.

Every accepted ADC pair contributes to online metrics. The six saved event
frames per pulse are NOT a full-rate waveform. Rejected pairs are NOT filled
in. Crossing/settling resolution is limited by the accepted sample spacing;
diagnostic quantization is 0.1mA/0.1mV (electrical speed: 0.01rad/s).
"""
import argparse
import ctypes as ct
import hashlib
import json
from pathlib import Path
import struct
from foc_path_profile_report import symbols
from loaded_fsm_snapshot_report import decode as decode_safety
from foc_output_gate_evidence_report import decode as decode_gate_evidence

ROOT=Path(__file__).resolve().parents[1]
ELF=ROOT/'foc2_app_a/build/CurrentStepAbDiagnostic/foc2.elf'
TARGETS=(.1,.1,.2,.2,.3,.3,-.1,-.1,-.2,-.2)
EVENTS=('baseline','10_percent','90_percent','peak','last_high','last_zero')


class Frame(ct.LittleEndianStructure):
    _fields_=[('us',ct.c_uint32),('seq',ct.c_uint32)]+[(k,ct.c_int16) for k in
        'iq_ref iq id vq vd int_q int_d out_q out_d omega'.split()]+[
        ('flags',ct.c_uint16),('fault',ct.c_uint16)]


class Metric(ct.LittleEndianStructure):
    _fields_=[(k,ct.c_int32) for k in 'baseline_sum baseline tail_sum peak'.split()]+[
        (k,ct.c_uint32) for k in
        'baseline_n tail_n high_n t10_us t90_us settle_us gaps last_seq crossings valid_mask'.split()]+[
        ('last_side',ct.c_int8),('clipped',ct.c_uint8),('reserved',ct.c_uint8*2)]


class Capture(ct.LittleEndianStructure):
    _fields_=[('rows',(Frame*6)*10),('failure',Frame),('metrics',Metric*10)]+[
        (k,ct.c_uint32) for k in 'start_us encoder_before last_us'.split()]+[
        (k,ct.c_uint8) for k in
        'state reason used prepared admitting step phase reset_pi positive_pass completed failure_valid reserved'.split()]


def frame(row):
    result={k:getattr(row,k) for k in ('us','seq','flags','fault')}
    result.update({k:getattr(row,k)/10000 for k in
        'iq_ref iq id vq vd int_q int_d out_q out_d'.split()})
    result.update(electrical_speed_rad_s=row.omega/100,
                  voltage_saturated=bool(row.flags&4),quantization_clipped=bool(row.flags&8))
    return result


def segment(s,k):
    m=s.metrics[k];target=TARGETS[k];amp=abs(target)
    events={name:frame(s.rows[k][j]) for j,name in enumerate(EVENTS) if m.valid_mask&(1<<j)}
    complete=k<s.completed and 'last_zero' in events
    if not m.high_n:
        return dict(step=k,pi='A_NEW' if k%2==0 else 'B_OLD',target_a=target,status='NOT_RUN',events=events)
    last_high=events.get('last_high',{}).get('us',0)%80000-20000
    crossing=all(v!=0xffffffff for v in (m.t10_us,m.t90_us)) and m.t90_us>=m.t10_us
    settled=m.settle_us!=0xffffffff and last_high-m.settle_us>=5000
    mean=m.tail_sum/m.tail_n/10000 if m.tail_n else None
    overshoot=max(0.,(m.peak/10000-amp)/amp*100)
    valid=bool(complete and not m.clipped and m.baseline_n>=80 and m.tail_n>=80 and m.high_n>=480)
    return dict(step=k,pi='A_NEW' if k%2==0 else 'B_OLD',target_a=target,
        status='MEASURED' if valid else 'INCOMPLETE_OR_INVALID',
        rise_10_90_ms=(m.t90_us-m.t10_us)/1000 if crossing else None,
        rise_below_one_sample_resolution=bool(crossing and m.t90_us==m.t10_us),
        peak_iq_a=(1 if target>0 else -1)*m.peak/10000,
        overshoot_percent=overshoot,settling_5percent_ms=m.settle_us/1000 if settled else None,
        tail_mean_iq_a=mean,steady_error_a=mean-target if mean is not None else None,
        ringing=bool(m.crossings>=4),band_side_crossings=m.crossings,
        accepted_high_samples=m.high_n,baseline_samples=m.baseline_n,tail_samples=m.tail_n,
        rejected_or_missing_pairs=m.gaps,quantization_clipped=bool(m.clipped),events=events)


def compare_segments(rows,safety_ok):
    result=[]
    for k in range(0,10,2):
        a,b=rows[k:k+2]
        usable=(safety_ok and a['status']==b['status']=='MEASURED' and
                not a['rejected_or_missing_pairs'] and not b['rejected_or_missing_pairs'] and
                all(r[f] is not None for r in (a,b) for f in
                    ('rise_10_90_ms','settling_5percent_ms','steady_error_a')))
        if not usable:
            result.append(dict(target_a=TARGETS[k],verdict='INSUFFICIENT_EVIDENCE'));continue
        checks=dict(faster_rise=a['rise_10_90_ms']<b['rise_10_90_ms'],
            overshoot_not_worse=a['overshoot_percent']<=b['overshoot_percent'],
            shorter_settling=a['settling_5percent_ms']<b['settling_5percent_ms'],
            steady_error_not_worse=abs(a['steady_error_a'])<=abs(b['steady_error_a'])+.0001,
            no_marked_ringing=not a['ringing'] and not b['ringing'])
        result.append(dict(target_a=TARGETS[k],checks=checks,
            verdict='NEW_MEETS_ALL' if all(checks.values()) else 'MIXED_OR_NOT_BETTER'))
    return result


def decode_capture(data,safety=None):
    if len(data)!=ct.sizeof(Capture):raise ValueError('Step ABI length mismatch')
    s=Capture.from_buffer_copy(data)
    if s.state<3 or s.state>5 or s.completed>10:raise ValueError('Need stopped terminal diagnostic capture')
    rows=[segment(s,k) for k in range(10)]
    timing=safety['timing'] if safety else None
    safety_ok=bool(safety and not safety['first_fault']['valid'] and
        not timing['deadline_miss'] and not timing['actual_late_count'] and
        timing['actual_commit_count'] and timing['actual_margin_min_us']>0 and s.reason==0)
    return dict(state=s.state,reason=s.reason,completed=s.completed,positive_pass=bool(s.positive_pass),
        event_trace_only=True,sample_quantization_a=.0001,nominal_sample_us=50,
        time_origin='accepted ADC reference issue; includes unchanged one-cycle PWM delay',
        settling_definition='last entry into +/-5% band, >=5ms observed in band before pulse end',
        ringing_definition='>=4 alternating excursions beyond opposite +/-5% band sides',
        safety=safety,timing_qualified=safety_ok,segments=rows,
        comparisons=compare_segments(rows,safety_ok),
        failure_frame=frame(s.failure) if s.failure_valid else None)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--elf',type=Path,default=ELF)
    p.add_argument('--ram',type=Path)
    p.add_argument('--flash',type=Path)
    p.add_argument('--receipt',type=Path,help='Same-session JSON: halted, outputs_off, vtor and hashes of elf/bin/ram/flash')
    p.add_argument('--out',type=Path)
    args=p.parse_args()
    if args.ram:
        if not args.flash or not args.receipt:p.error('RAM requires matching full Flash and stopped same-session receipt')
        elf=args.elf.read_bytes();image=args.elf.with_suffix('.bin').read_bytes()
        ram=args.ram.read_bytes();flash=args.flash.read_bytes();proof=json.loads(args.receipt.read_text('utf-8'))
        digest=lambda x:hashlib.sha256(x).hexdigest()
        if (len(ram)!=0x20000 or len(flash)!=0x80000 or flash[0x8000:0x8000+len(image)]!=image or
            not proof.get('halted') or not proof.get('outputs_off') or proof.get('vtor')!=0x08008000 or
            any(proof.get(k+'_sha256')!=digest(v) for k,v in dict(elf=elf,image=image,ram=ram,flash=flash).items())):
            p.error('Stopped candidate A image/capture identity mismatch')
        table=symbols(args.elf);address,size=table['current_step_ab']
        if size!=ct.sizeof(Capture):p.error('ELF ABI mismatch')
        if struct.unpack_from('<I',image,4)[0]!=(table['Reset_Handler'][0]|1):p.error('ELF/BIN reset mismatch')
        report=decode_capture(ram[address-0x20000000:address-0x20000000+size],decode_safety(ram,args.elf))
        report['gate_evidence']=decode_gate_evidence(ram,args.elf)
    else:
        report=dict(status='NOT_MEASURED',hardware_access=False,preset=args.elf.parent.name,
            manual_command='MOTOR TEST CURRENT STEP AB CONFIRM',
            plan=[dict(step=k,pi='A_NEW' if k%2==0 else 'B_OLD',iq_a=t,
                       zero_pre_ms=20,pulse_ms=30,zero_post_ms=30) for k,t in enumerate(TARGETS)],
            negative_gate='all six positive pulses pass; fault stops whole batch; never retry automatically')
    output=json.dumps(report,ensure_ascii=False,indent=2)+'\n'
    if args.out:args.out.write_text(output,encoding='utf-8')
    print(output)


if __name__=='__main__':main()
