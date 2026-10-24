"""Decode first identification continuity failure from saved RAM; no device IO."""
import argparse
import hashlib
import json
from pathlib import Path
import struct

PREFIX_SIZE=1660  # Unchanged bounded-reject identification prefix.
IDENT_SIZE=1724
KEYS='prev_seq prev_us seq us delta_seq delta_us flags valid adc_seq frame_seq pair_us hold_before hold_now path context_valid'.split()


def decode(raw,offset=0,*,max_dt_us=55):
    # Caller must use the exact image's policy; never infer a limit from dt.
    if max_dt_us not in (55,100):raise ValueError('Explicit known timing policy required')
    if offset<0 or len(raw)<offset+IDENT_SIZE:
        raise ValueError('Complete 1724-byte timing identification ABI required')
    t=dict(zip(KEYS,struct.unpack_from('<15I',raw,offset+PREFIX_SIZE)))
    out=dict(snapshot=t,physical_adc_aperture_measured=False)
    if t['valid']!=1:
        out['classification']='NO_CONTINUITY_SNAPSHOT; do not infer failed seq/dt'
        return out
    ds=(t['seq']-t['prev_seq'])&0xffffffff
    dt=(t['us']-t['prev_us'])&0xffffffff
    flags=int(ds!=1)|(int(dt<45)<<1)|(int(dt>max_dt_us)<<2)
    if not flags or (ds,dt,flags)!=(t['delta_seq'],t['delta_us'],t['flags']):
        raise ValueError('Inconsistent frozen seq/dt snapshot')
    out['failed_conditions']=[name for bit,name in ((1,'sequence_delta_not_1'),
        (2,'software_dt_below_45us'),(4,'software_dt_above_%dus'%max_dt_us)) if flags&bit]
    out['classification']='ACCEPTED_SEQUENCE_GAP' if flags&1 else 'SOFTWARE_TIMESTAMP_INTERVAL'
    if t['context_valid']==1:
        if (t['adc_seq'],t['frame_seq'],t['pair_us'])!=(t['seq'],t['seq'],t['us']):
            raise ValueError('Reference-owner context does not match failure frame')
        out['hold_since_last_reference']=(t['hold_now']-t['hold_before'])&0xffffffff
        if flags&1 and out['hold_since_last_reference']:
            out['classification']='ACCEPTED_SEQUENCE_GAP_WITH_DISCRIMINATOR_HOLD'
    else:
        out['context_warning']='Context not published; no hold attribution'
    out['limitation']='Software owner timestamps; cannot prove physical ADC loss/aperture jitter'
    return out


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--receipt',type=Path,required=True)
    p.add_argument('--elf',type=Path,required=True)
    a=p.parse_args();r=json.loads(a.receipt.read_text('utf-8'))
    raw=Path(r['ram_capture']).read_bytes()
    if len(raw)!=0x20000 or hashlib.sha256(raw).hexdigest()!=r['ram_sha256']:
        raise ValueError('Saved RAM capture hash/size mismatch')
    if hashlib.sha256(a.elf.read_bytes()).hexdigest()!=r['elf_sha256']:
        raise ValueError('Same-session ELF required')
    import friction_fsm_board as board
    addr,size=board.symbols(a.elf)['motor_ident']
    if size!=IDENT_SIZE:raise ValueError('Wrong firmware ABI; old runs have no failed-frame snapshot')
    print(json.dumps(decode(raw,addr-0x20000000),indent=2))


if __name__=='__main__':main()
