"""Files-only decoder for candidate contact-hold V2, never touches a probe."""
import math
import struct
from dob_load_speed_decode import POLICY,META,STATE_NAMES,REASONS as OLD_REASONS

REASONS=OLD_REASONS+['CONTACT_HOLD','CONTACT_REACQUIRE']
EVENT='timestamp_us reason phase flags high_us release_us base_rpm selected_rpm mean_a previous_ref_rpm previous_accel_rpm_s sample_index'.split()


def decode(ram,syms):
    def block(name):
        addr,size=syms[name];offset=addr-0x20000000
        if not 0<=offset<=len(ram)-size:raise ValueError('V2 RAM bounds')
        return ram[offset:offset+size]
    if syms.get('dob_load_speed',(0,0))[1]!=68:raise ValueError('V2 requires68-byte state ABI')
    values=struct.unpack('<12I2f3I',block('dob_load_speed'))
    policy=dict(zip(POLICY,values[:8]));meta=dict(zip(META,values[8:15]))
    meta.update(contact_held=values[15],reacquire_us=values[16])
    if policy['reason']>=len(REASONS) or meta['phase']>=len(STATE_NAMES):raise ValueError('V2 state enum')
    if not all(math.isfinite(meta[k]) for k in ('base_rpm','selected_rpm')):raise ValueError('V2 nonfinite state')
    if struct.unpack('<I',block('dob_trend_continuous_arena'))[0]!=syms['mechanical_capture'][0]:raise ValueError('V2 recorder not bound')
    raw=block('mechanical_capture');tail=raw[300:400]+raw[700:800]
    magic,count=struct.unpack_from('<2I',tail)
    if magic not in (0,0xD1500002) or bool(magic)!=bool(count):raise ValueError('V2 trace ABI')
    if not magic and any(tail):raise ValueError('V2 unexpected tail owner')
    events=[];ordinals=list(range(count)) if count<=4 else [0]+list(range(count-3,count))
    for n in ordinals:
        slot=0 if n==0 else 1+(n-1)%3
        item=dict(zip(EVENT,struct.unpack_from('<6I5fI',tail,8+48*slot)))
        if item['phase']>=len(STATE_NAMES) or item['reason']>=len(REASONS):raise ValueError('V2 event enum')
        if not all(math.isfinite(item[k]) for k in EVENT[6:11]):raise ValueError('V2 nonfinite event')
        flags=item['flags']
        item.update(from_slow=flags&1,to_slow=(flags>>1)&1,valid=(flags>>2)&1,
            trend_valid=(flags>>3)&1,level=(flags>>4)&7,trend=(flags>>7)&3,
            event_ordinal=n+1,phase_name=STATE_NAMES[item['phase']],reason_name=REASONS[item['reason']])
        events.append(item)
    if meta['slow_epochs']>meta['samples'] or meta['invalid_epochs']>meta['samples']:raise ValueError('V2 counters')
    policy['reason_name']=REASONS[policy['reason']];meta['phase_name']=STATE_NAMES[meta['phase']]
    return dict(abi=2,policy=policy,telemetry=meta,event_count=count,events=events,
        middle_events_overwritten=max(0,count-4),first_and_latest3=True,
        meaning='Target before original S-curve; contact hold is not proof of fresh DOB feedback or output power state.')
