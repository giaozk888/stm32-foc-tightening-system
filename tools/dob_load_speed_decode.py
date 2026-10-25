"""Files-only, halted-RAM decoder for the opt-in load-speed board candidate."""
import math
import struct
from pathlib import Path

REASONS=['BASE','HIGH_CONFIRM','SLOW','RELEASE_CONFIRM','SHORT_GAP','LONG_GAP','PHASE','DISABLED']
STATE_NAMES='IDLE PRECHECK RUNDOWN_START RUNDOWN CONTACT_CONFIRM TIGHTEN HOLD DONE NO_ROTATION TIMEOUT FAULT'.split()
POLICY='slow high_us release_us last_good_us entered_us transitions reason previous_good'.split()
META='samples slow_epochs invalid_epochs last_epoch_us base_rpm selected_rpm phase'.split()
EVENT='timestamp_us reason phase from_slow to_slow valid level trend_valid trend high_us release_us base_rpm selected_rpm mean_a previous_ref_rpm previous_accel_rpm_s'.split()


def decode(ram, syms):
    def block(name):
        a,n=syms[name];offset=a-0x20000000
        if not 0<=offset<=len(ram)-n:raise ValueError('Load-speed RAM bounds')
        return ram[offset:offset+n]
    if syms.get('dob_load_speed',(0,0))[1]!=60:raise ValueError('Matching load-speed60-byte ABI required')
    values=struct.unpack('<12I2fI',block('dob_load_speed'));policy=dict(zip(POLICY,values[:8]));meta=dict(zip(META,values[8:]))
    if policy['reason']>=len(REASONS) or meta['phase']>=len(STATE_NAMES):raise ValueError('Load-speed enum ABI')
    raw=block('mechanical_capture');pointer=struct.unpack('<I',block('dob_trend_continuous_arena'))[0]
    if pointer!=syms['mechanical_capture'][0]:raise ValueError('Recorder not bound; no invented telemetry')
    tail=raw[300:400]+raw[700:800];magic,count=struct.unpack_from('<2I',tail)
    if magic not in (0,0xD1500001) or bool(count)!=bool(magic):raise ValueError('Load-speed trace ABI')
    if not magic and any(tail):raise ValueError('Unexpected tail owner')
    slots=[]
    indices=list(range(count)) if count<=3 else [0]+sorted((count-1,count-2))
    for ordinal in indices:
        slot=0 if ordinal==0 else 1+(ordinal-1)%2
        item=dict(zip(EVENT,struct.unpack_from('<11I5f',tail,8+slot*64)))
        if item['phase']>=len(STATE_NAMES) or item['reason']>=len(REASONS):raise ValueError('Load-speed event enum')
        if not all(math.isfinite(item[k]) for k in EVENT[11:]):raise ValueError('Nonfinite load speed event')
        item.update(event_ordinal=ordinal+1,phase_name=STATE_NAMES[item['phase']],reason_name=REASONS[item['reason']])
        slots.append(item)
    policy['reason_name']=REASONS[policy['reason']];meta['phase_name']=STATE_NAMES[meta['phase']]
    if meta['slow_epochs']>meta['samples'] or meta['invalid_epochs']>meta['samples']:raise ValueError('Load-speed counter closure')
    return dict(abi=1,policy=policy,telemetry=meta,event_count=count,events=slots,
        middle_events_overwritten=max(0,count-3),first_and_latest2=True,
        meaning='Selection before S-curve. Event ref/accel are previous completed trajectory values; not current applied speed. Last state is not a power-state proof.')


def load(ram_path,elf):
    from foc_path_profile_report import symbols
    return decode(Path(ram_path).read_bytes(),symbols(elf))
