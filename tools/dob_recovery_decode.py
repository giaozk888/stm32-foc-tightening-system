"""Read passive recovery partitions from HALTED RAM or a synthetic native fixture.
Never connect to a board, change configuration or reconstruct absent epochs.
"""
import argparse
import csv
import hashlib
import json
from pathlib import Path
import struct
from foc_path_profile_report import symbols
HEADER='abi calls records overwritten short_gaps active last_us phase warm_us clock_errors completed interrupted last_classifier_resets pending_first_invalid_us first_invalid_0 first_invalid_1 first_invalid_2'.split()
FIELDS='start_us end_us low_us qualify_us warm_us quality_us window_us level_us trend_us other_us warm_credit_us flags_reason'.split()
PHASES='low_us qualify_us warm_us quality_us window_us level_us trend_us other_us'.split()
NAMES=['ready','low_speed','initial_direction_qualification','dob_warmup','input_or_Id_quality_wait',
    'classification_window','level_confirmation','trend_confirmation','other']

def record(data,first_invalid):
    r=dict(zip(FIELDS,struct.unpack('<12I',data)))
    span=(r['end_us']-r['start_us'])&0xffffffff;total=sum(r[k] for k in PHASES)
    if span>=0x80000000 or total!=span:raise ValueError('Recovery wall-time partition does not close')
    flags=r['flags_reason'];complete=bool(flags&(1<<16));interrupted=bool(flags&(1<<17))
    r.update(wall_us=span,first_invalid_us=first_invalid,
        lead_in_us=(r['start_us']-first_invalid)&0xffffffff,
        initial=bool(flags&(1<<19)),starts_at_classifier_reset=bool(flags&(1<<20)),
        multiple_classifier_resets=bool(flags&(1<<21)),complete=complete,interrupted=interrupted,
        timing_qualified=complete and not interrupted and not bool(flags&(1<<18)),
        observed_status_or=flags&65535,partition_sum_us=total)
    return r

def decode(header,storage):
    if len(header)!=68 or len(storage)!=200:raise ValueError('Recovery ABI/buffer length')
    h=dict(zip(HEADER,struct.unpack('<17I',header)))
    if h['abi']!=1 or h['active'] not in (0,1) or h['phase']>=len(NAMES):raise ValueError('Recovery ABI/state invalid')
    if h['overwritten']!=max(0,h['records']-3) or h['records']!=h['completed']+h['interrupted']:
        raise ValueError('Recovery record counter closure')
    rows=[];count=min(3,h['records']);first=h['records']-count
    for index in range(first,h['records']):
        slot=index%3;r=record(storage[slot*48:slot*48+48],h['first_invalid_'+str(slot)])
        r.update(sequence=index+1,slot=slot);rows.append(r)
    pending=record(storage[144:192],h['pending_first_invalid_us']) if h['active'] else None
    if pending and pending['complete']:raise ValueError('Pending record cannot claim completion')
    return dict(abi=1,header=h,current_phase=NAMES[h['phase']],records=rows,pending=pending,
        complete_history=h['overwritten']==0,
        semantics='Task-epoch left-held exclusive wall phases; first invalid and actual classifier reset separated. Warm credit is observed internal elapsed change, not another additive delay. Clock gaps flagged uncertain; no interpolation. Not brake detection latency.')

def load(fixture=None,ram=None,elf=None):
    if fixture:
        data=fixture.read_bytes()
        if len(data)!=268:raise ValueError('Synthetic fixture length')
        result=decode(data[:68],data[68:]);result['source_kind']='synthetic_native_fixture'
        result['source']=str(fixture);result['sha256']=hashlib.sha256(data).hexdigest()
        return result
    if ram is None or elf is None:raise ValueError('Saved HALTED RAM and matching candidate ELF required')
    data=ram.read_bytes();syms=symbols(elf)
    a,n=syms['dob_recovery_timing']
    if n!=68:raise ValueError('Candidate recovery global ABI')
    c,size=syms['mechanical_capture']
    if size!=4712:raise ValueError('Preserved mechanical arena ABI')
    def read(address,length):
        offset=address-0x20000000
        if not 0<=offset<=len(data)-length:raise ValueError('RAM bounds')
        return data[offset:offset+length]
    storage=read(c+300,100)+read(c+700,100)
    result=decode(read(a,n),storage)
    result.update(source_kind='saved_halted_RAM',source=str(ram),elf=str(elf),
        sha256=hashlib.sha256(data).hexdigest(),elf_sha256=hashlib.sha256(elf.read_bytes()).hexdigest())
    return result

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--fixture',type=Path)
    p.add_argument('--ram',type=Path);p.add_argument('--elf',type=Path);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args()
    if bool(a.fixture)==bool(a.ram or a.elf):p.error('Choose one fixture or paired --ram/--elf')
    result=load(a.fixture,a.ram,a.elf);a.output.write_text(json.dumps(result,indent=2)+'\n')
    if result['records']:
        with a.output.with_suffix('.csv').open('w',newline='',encoding='utf-8') as f:
            writer=csv.DictWriter(f,fieldnames=result['records'][0]);writer.writeheader();writer.writerows(result['records'])
    print(json.dumps(result,indent=2))
if __name__=='__main__':main()
