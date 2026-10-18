"""Offline TWO_SAMPLE evidence audit. Never imports or opens a board interface.

Absent frames/fields remain None. End-state candidate is AFTER the last Push;
it must not be used as that Push's candidate_before to invent d_candidate=0.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import struct
import subprocess

import current_fault_trace_report as trace

ARM_OBJDUMP = 'D:/software/arm/bin/arm-none-eabi-objdump.exe'
LAYOUT = (300,248,48,36,40,44,45,296)
KEYS = ('samples suspect spike transition unresolved_total unresolved_consecutive '
        'unresolved_max fault recovered reference_u reference_v candidate_u '
        'candidate_v state last_path').split()


def verify_layout(path):
    text = subprocess.check_output([ARM_OBJDUMP,'-s','-j','.rodata',str(path)],text=True)
    words = []
    for line in text.splitlines():
        m = re.match(r'^\s+[0-9a-f]+\s+((?:[0-9a-f]{8}\s+){1,4})',line)
        if m:
            words.extend(m[1].split())
    if struct.unpack('<8I',bytes.fromhex(''.join(words))) != LAYOUT:
        raise ValueError('ARM layout mismatch; do not guess SRAM fields')


def summarize(receipt, end):
    t = receipt['trace']['header']
    rows = receipt['trace']['frames']
    fault = receipt['first_fault']
    seq = int(receipt['samples'][-1]['fault']['SEQ'])
    matching = [r for r in rows if r['seq'] == seq and r['protection_fault']]
    if end['state'] != 1 or end['last_path'] != 3 or end['unresolved_consecutive'] != 3:
        raise ValueError('Not the reported three-unresolved end-state')
    ref = [end['reference_u'],end['reference_v']]
    raw = [fault['raw_u'],fault['raw_v']]
    inferred = []
    for count in (1,2,3):
        last = count == 3
        inferred.append(dict(seq=(seq-3+count)&0xffffffff,
            evidence='last frame endpoint only' if last else 'NOT_CAPTURED; sequence/counter inferred',
            raw=raw if last else None, old_reference=ref,
            candidate_before=None, candidate_after=raw if last else None,
            d_old=max(abs(raw[i]-ref[i]) for i in (0,1)) if last else None,
            d_candidate=None, discriminator_state='SUSPECT', DISC_EXEC='inferred 1',
            confirmed_spike=end['spike'],confirmed_transition=end['transition'],
            unresolved_consecutive=count,CUR_CONFIRM=None,PI_EXEC='inferred 0',
            PWM_PENDING=None,fault=1 if last else 0))
    return dict(fault_seq=seq,trace_first_seq=rows[0]['seq'],trace_last_seq=rows[-1]['seq'],
        trace_freeze_reason=t['freeze_reason'],trace_fault_seq=t['fault_seq'],
        fault_window_captured=bool(matching),
        missing_frame_fields=['old_reference','candidate','d_old','d_candidate',
            'discriminator_state','confirmed_spike','confirmed_transition','unresolved_count',
            'PWM_PENDING (trace pending_before is CUR_CONFIRM, not PWM pending)'],
        terminal_validation=end,partial_fault_evolution=inferred,
        classification='UNDETERMINED: A/B/C/D/E/F not established by missing fault window',
        production_fix_justified=False,real_fault_regression_available=False,
        note='d_candidate uses candidate BEFORE Push; last saved candidate was overwritten by the last unresolved frame')


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--receipt',type=Path,required=True)
    p.add_argument('--elf',type=Path,required=True)
    p.add_argument('--layout-object',type=Path,required=True)
    args = p.parse_args()
    verify_layout(args.layout_object)
    r = json.loads(args.receipt.read_text('utf-8'))
    image = args.elf.with_suffix('.bin').read_bytes()
    if (hashlib.sha256(image).hexdigest()!=r['image_sha256'] or
            hashlib.sha256(args.elf.read_bytes()).hexdigest()!=r['elf_sha256']):
        raise ValueError('Exact captured BIN/ELF required')
    flash,ram = Path(r['final_backup']).read_bytes(),Path(r['ram_backup']).read_bytes()
    if (len(flash)!=0x80000 or len(ram)!=0x20000 or
            r['snapshot_vtor']!=0x08008000 or flash[0x8000:0x8000+len(image)]!=image or
            hashlib.sha256(flash).hexdigest()!=r['final_sha256']):
        raise ValueError('Same-session captured A identity mismatch')
    symbols = trace.schema.symbols(args.elf)
    address,size = symbols['cl_safety']
    if size!=LAYOUT[0]:
        raise ValueError('Safety layout mismatch')
    end = dict(zip(KEYS,struct.unpack_from('<9I4H2B',ram,address-0x20000000+LAYOUT[1])))
    address,size = symbols['foc_current_fault_trace']
    header,frames = trace.decode(ram[address-0x20000000:address-0x20000000+size])
    if header!=r['trace']['header'] or frames!=r['trace']['frames']:
        raise ValueError('Receipt trace differs from decoder/raw RAM')
    print(trace.table(header,frames))
    print(json.dumps(summarize(r,end),ensure_ascii=False,indent=2))


if __name__=='__main__':
    main()
