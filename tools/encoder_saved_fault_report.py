"""Read-only saved-RAM encoder diagnosis; no serial/debugger/reset operations."""
import argparse
import hashlib
import json
from pathlib import Path
import struct

FAULT_KEYS=('valid status phase frame started_us now_us deadline_us guard_us spi_sr spi_cr1 spi_cr2 '
            'dma_isr rx_ndtr tx_ndtr rx_ccr tx_ccr tim_sr tim_dier ipsr tim_entry_valid tim_entry_us '
            'tim_entry_sr tim_entry_dier tim_entry_ccr2 tim_entry_late_us guard_max_late_us').split()
SAMPLE_KEYS='status sequence sample_us completed_us elapsed_us raw response errfl errfl_valid recovered'.split()


def decode(receipt,elf):
    return decode_saved(json.loads(Path(receipt).read_text('utf-8')),elf)


def decode_saved(r,elf):
    elf=Path(elf)
    ram=Path(r['ram_capture']).read_bytes()
    digest=lambda b:hashlib.sha256(b).hexdigest()
    if len(ram)!=0x20000 or digest(ram)!=r['ram_sha256'] or digest(elf.read_bytes())!=r['elf_sha256']:
        raise ValueError('Exact saved RAM and same-session ELF required')
    import friction_fsm_board as board
    symbols=board.symbols(elf)
    def at(name,size):
        addr,n=symbols[name]
        if n!=size or addr<0x20000000 or addr+n>0x20020000:
            raise ValueError('Unexpected encoder symbol ABI: '+name)
        return addr-0x20000000
    f=dict(zip(FAULT_KEYS,struct.unpack_from('<26I',ram,at('first_fault',104))))
    po=at('publication',60)
    banks=[dict(zip(SAMPLE_KEYS,struct.unpack_from('<5I3H2B',ram,po+k*28))) for k in (0,1)]
    generation=struct.unpack_from('<I',ram,po+56)[0]
    en=dict(zip('ops context state started_us deadline_us guard_us word_rx_us attempts successes failures max_elapsed_us'.split(),
                struct.unpack_from('<11I',ram,at('engine',88))))
    scalars={}
    for key in ('diagnostic_fault_status','timeouts','dma_errors','schedule_misses','control_stale',
                'defer_urgent','defer_fault_serviced','defer_fault_flags_valid','encoder_timeout_reason'):
        size=1 if key=='encoder_timeout_reason' else 4  # ARM -fshort-enums.
        off=at(key,size);scalars[key]=int.from_bytes(ram[off:off+size],'little')
    diff=lambda a,b:(a-b)&0xffffffff
    budget=diff(en['deadline_us'],en['started_us'])
    if budget not in (200,400):raise ValueError('Unknown captured transaction deadline policy')
    success=next((s for s in banks if s['status']==0),None)
    failure=next((s for s in banks if s['status']==2),None)
    same_attempt_success_then_timeout=bool(f['valid']==1 and f['status']==2 and f['phase']==0 and
        success and failure and failure['sequence']==success['sequence']+1 and
        success['sample_us']==failure['sample_us']==en['word_rx_us'] and
        diff(success['completed_us'],en['started_us'])==success['elapsed_us'] and
        diff(failure['completed_us'],en['started_us'])==failure['elapsed_us'] and
        success['elapsed_us']<budget<=failure['elapsed_us'] and
        en['attempts']==en['successes'] and en['failures']==1)
    return dict(receipt=r.get('receipt_path',''),first_fault=f,engine=en,publication_generation=generation,
        publication_banks=banks,counters=scalars,
        fault_elapsed_us=diff(f['now_us'],f['started_us']),
        fault_after_deadline_us=diff(f['now_us'],f['deadline_us']),
        same_attempt_success_then_timeout=same_attempt_success_then_timeout,
        transaction_budget_us=budget,
        success_margin_us=budget-success['elapsed_us'] if same_attempt_success_then_timeout else None,
        last_success_margin_us=budget-success['elapsed_us'] if success else None,
        limitation=('Saved state proves duplicate terminal publication; exact interrupt PC/entry time was not captured'
                    if same_attempt_success_then_timeout else
                    'No same-attempt success/timeout pair in saved banks; exact interrupt PC/entry time was not captured'))


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--receipt',type=Path,required=True);p.add_argument('--elf',type=Path,required=True)
    a=p.parse_args();print(json.dumps(decode(a.receipt,a.elf),indent=2))


if __name__=='__main__':main()
