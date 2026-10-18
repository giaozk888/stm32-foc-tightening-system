"""Offline same-image SRAM decoder; no device access or motor operations."""
import argparse
import hashlib
import json
import struct
from pathlib import Path
import foc_path_profile_report as schema

ROOT=Path(__file__).resolve().parents[1]
IRQ=('TIM7','TIM2','DMA1_CH4_RX','DMA1_CH5_TX')

def frame(w):
    valid=bool(w[11])
    result=dict(valid=valid,wall_cycles=w[0],wall_us=w[0]/170,
        preempt_cycles=w[1],preempt_us=w[1]/170,
        active_est_cycles=w[2],active_est_us=w[2]/170,
        dominant=IRQ[w[12]] if w[12]<4 else 'INVALID',path=w[13],
        irq={name:dict(cycles=w[3+i],us=w[3+i]/170,count=w[7+i])
             for i,name in enumerate(IRQ)})
    if valid and (sum(w[3:7])!=w[1] or w[1]+w[2]!=w[0]):
        raise ValueError('Invalid same-frame accounting identity')
    return result

def decode(elf,ram,flash,vtor):
    image=elf.with_suffix('.bin').read_bytes()
    sym=schema.symbols(elf)
    if (vtor!=0x08008000 or len(flash)!=0x80000 or len(ram)!=0x20000 or
            flash[0x8000:0x8000+len(image)]!=image or
            struct.unpack_from('<I',image,4)[0]!=(sym['Reset_Handler'][0]|1)):
        raise ValueError('Complete captures and matching A ELF/BIN/VTOR required')
    def words(name,size):
        addr,actual=sym[name]; off=addr-0x20000000
        if size!=actual or not 0<=off<=len(ram)-size:
            raise ValueError('Unexpected pinned RAM schema: '+name)
        return struct.unpack_from('<'+'I'*(size//4),ram,off)
    def word(name): return words(name,4)[0]
    t=words('foc_preempt_timing',140)
    sources=words('foc_preempt_irq',64)
    actual=schema.pwm(words('foc_pwm_write_profile',128))
    hyp=schema.pwm(words('foc_pwm_duty_profile',128))
    actual.update(actual_late_count=word('foc_ccr_probe_hard_late'),
        blocked=word('foc_ccr_probe_blocked'),post_unsafe=word('foc_ccr_probe_post_unsafe'),
        latch_crossings=word('foc_ccr_probe_latch_late'))
    latch=words('foc_ccr_probe_latch_margin_min',4)[0]
    latch=struct.unpack('<i',struct.pack('<I',latch))[0]
    actual['latch_margin_min_us']=latch/170 if actual['points'] else None
    priorities=words('foc_probe_irq_priority',28)
    result=dict(bin_sha256=hashlib.sha256(image).hexdigest(),
        elf_sha256=hashlib.sha256(elf.read_bytes()).hexdigest(),
        timing=dict(frames=t[0],invalid=t[1],wall_max_us=t[2]/170,
            preempt_max_us=t[3]/170,active_est_max_us=t[4]/170,
            deadline_miss=t[5],observer_tail_max_us=t[6]/170,
            worst_preempt=frame(t[7:21]) if t[0] and t[3] else None,
            first_miss=frame(t[21:35]) if t[5] else None),
        irq={name:dict(exclusive_total_cycles=sources[4*i],count=sources[4*i+1],
            inclusive_max_single_us=sources[4*i+2]/170,invalid=sources[4*i+3])
            for i,name in enumerate(IRQ)},
        priorities=dict(ok=word('foc_probe_priorities_ok'),
            unexpected=word('foc_probe_unexpected_irq'),
            values=dict(zip((*IRQ,'ADC','SysTick','PendSV'),priorities))),
        actual_ccr=actual,hypothetical=hyp,
        physical_shadow_latch_directly_observed=False,motor_qualified=False)
    if not actual['points']:
        verdict='UNRESOLVED_NO_VALID_ACTUAL_COMMITS'
    elif actual['actual_late_count'] or actual['latch_crossings']:
        verdict='ACTUAL_TRANSACTION_MISSES_TARGET_OR_CROSSES_UEV'
    elif actual['late_update_count']:
        verdict='POSITIVE_MARGIN_INSIDE_EXISTING_GUARD_REVIEW_UNCERTAINTY'
    else:
        verdict='OBSERVED_ACTUAL_TRANSACTION_HAS_GUARD_MARGIN_NOT_WCET_PROOF'
    result['pwm_verdict']=verdict
    return result

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--elf',type=Path,required=True)
    p.add_argument('--ram',type=Path,required=True)
    p.add_argument('--flash',type=Path,required=True)
    p.add_argument('--vtor',type=lambda v:int(v,0),required=True)
    a=p.parse_args()
    print(json.dumps(decode(a.elf,a.ram.read_bytes(),a.flash.read_bytes(),a.vtor),indent=2))

if __name__=='__main__': main()
