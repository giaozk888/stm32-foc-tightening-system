"""Read stopped SB2 fault evidence; replay command policies, NOT motor motion."""
import hashlib
import json
from pathlib import Path
import struct

from foc_path_profile_report import symbols

ROOT=Path(__file__).resolve().parents[1]
RECEIPT=ROOT/'tmp/voltage-x2-fsm-1792313964816534200.json'
ELF=ROOT/'foc2_app_a/build/VoltageX2Trial/foc2.elf'
BIN_SHA='6f83652e152f569d3830ca2b5d1b9033c475140967b1db34f5bdc5ebed969098'
ELF_SHA='6445cf694132c6c2a9fb95abf6e29f525d989c5f00fc2d95e4ac35780b885f8e'


def trace():
    r=json.loads(RECEIPT.read_text('utf-8')); image=ELF.with_suffix('.bin').read_bytes()
    flash=Path(r['final_capture']).read_bytes(); ram=Path(r['ram_capture']).read_bytes()
    digest=lambda data:hashlib.sha256(data).hexdigest()
    if (digest(image)!=BIN_SHA or digest(ELF.read_bytes())!=ELF_SHA or
            digest(flash)!=r['final_sha256'] or len(flash)!=0x80000 or len(ram)!=0x20000 or
            flash[0x8000:0x8000+len(image)]!=image or r.get('start_attempts')!=1 or
            not r.get('final_cpu_halted') or not r.get('final_outputs_off') or
            r['snapshot']['first_fault']['protection_flags']!=1024):
        raise ValueError('Exact stopped SB2 1.6V overspeed evidence required')
    table=symbols(ELF); address,size=table['cl_startup']; offset=address-0x20000000
    if size!=2000: raise ValueError('Exact startup-trace schema required')
    h=struct.unpack_from('<4I4B',ram,offset+1980)
    if h[1]!=1024 or not h[5] or not h[6] or h[4] or h[3]<32:
        raise ValueError('Frozen overspeed trace required')
    rows=[]
    for seq in range(h[3]-32,h[3]):
        v=struct.unpack_from('<3I4H10f',ram,offset+seq%32*60)
        row=dict(zip(('elapsed_us','adc_seq','encoder_us','raw_angle','u','v','reserved',
            'ref_rpm','instant_rpm','filtered_rpm','iq_ref_A','id_A','iq_A','vd_V','vq_V',
            'int_d_V','int_q_V'),v))
        row['inferred_speed_I_A']=row['iq_ref_A']-.003*(row['ref_rpm']-row['filtered_rpm'])
        rows.append(row)
    return rows


if __name__=='__main__':
    rows=trace()
    print(json.dumps(dict(offline_only=True,hardware_operations=0,rows=rows,
        limitation='Observed inputs only. Different current commands change motor motion; no predicted speed.'),indent=2))
