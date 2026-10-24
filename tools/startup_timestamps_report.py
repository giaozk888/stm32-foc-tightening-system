"""Five distinct startup timestamps; files only, no device access."""
import argparse
import hashlib
import json
from pathlib import Path
import struct
from foc_path_profile_report import symbols

NAMES=('valid t0_us t_iq_us t_motion_us t_speed_us t_stable_us motion_begin_us '
    'observations last_sample_us candidate_us forward_samples forward_counts reverse_counts '
    'sample_valid last_forward_us motion_direction direction iq_at_event_a speed_at_event_rpm').split()


def timings(s):
    flags={'t0_us':1,'t_iq_us':2,'t_motion_us':4,'t_speed_us':8,'t_stable_us':16}
    absolute={key:s[key] if s['valid']&bit else None for key,bit in flags.items()}
    delays={key.replace('_us','_delay_us'):(value-s['t0_us'])&0xffffffff
        if value is not None and s['valid']&1 else None for key,value in absolute.items()}
    return dict(absolute_us=absolute,relative_to_t0=delays,
        motion_window_begin_us=s['motion_begin_us'] if s['valid']&4 else None,
        iq_at_event_a=s['iq_at_event_a'] if s['valid']&2 else None,
        motion_direction=s['motion_direction'] if s['valid']&4 else None,
        speed_at_event_rpm=s['speed_at_event_rpm'] if s['valid']&8 else None,
        note='t_motion is encoder-evidence confirmation, not direct physical onset metrology. t_stable is the legacy 50ms confirmation EVENT, not backdated START_MS. Task observations are ~1ms, despite a 1MHz clock.')


def decode(receipt,elf):
    r=json.loads(receipt.read_text());ram=Path(r['ram_capture']).read_bytes()
    flash=Path(r['final_capture']).read_bytes();image=elf.with_suffix('.bin').read_bytes()
    if (len(ram)!=0x20000 or hashlib.sha256(ram).hexdigest()!=r.get('ram_sha256') or
        hashlib.sha256(flash).hexdigest()!=r['final_sha256'] or
        hashlib.sha256(elf.read_bytes()).hexdigest()!=r['elf_sha256'] or
        hashlib.sha256(image).hexdigest()!=r['image_sha256'] or
        flash[0x8000:0x8000+len(image)]!=image):raise ValueError('Exact Flash/RAM/ELF identity required')
    addr,size=symbols(elf)['startup_timestamps'];offset=addr-0x20000000
    if size!=76 or not 0<=offset<=len(ram)-size:raise ValueError('Startup ABI/bounds mismatch')
    s=dict(zip(NAMES,struct.unpack_from('<15Ii3f',ram,offset)))
    return dict(snapshot=s,timings=timings(s),hardware_access=False)


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--receipt',type=Path,required=True)
    p.add_argument('--elf',type=Path,required=True);a=p.parse_args()
    print(json.dumps(decode(a.receipt,a.elf),indent=2,allow_nan=False))


if __name__=='__main__':main()
