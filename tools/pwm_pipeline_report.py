"""Offline decoder for exact A-slot OneCyclePwmPipeline Flash/RAM captures.

No device access. The historical preemption decoder is intentionally left
unchanged: its TIM7 exclusive accounting must NOT label this lower IRQ.
"""
import argparse
import json
import struct
from pathlib import Path
import preempt_commit_report as base

def decode(elf,ram,flash,vtor):
    sym=base.schema.symbols(elf)
    for name in ('ProtectedLoop_PwmEntry','cl_pwm_pending','foc_pending_commit_max_cycles',
                 'foc_pending_generation_max_cycles','foc_tim7_preempt_max_cycles'):
        if name not in sym: raise ValueError('Not a one-cycle pipeline ELF: '+name)
    result=base.decode(elf,ram,flash,vtor)
    if result['priorities']['values']['TIM7']!=3:
        raise ValueError('Pipeline capture does not have software guard priority 3')
    def word(name):
        address,size=sym[name]; off=address-0x20000000
        if size!=4 or not 0<=off<=len(ram)-4: raise ValueError('Wrong word layout: '+name)
        return struct.unpack_from('<I',ram,off)[0]
    guard=result['irq']['TIM7']
    guard['service_wall_cycles_including_children']=guard.pop('exclusive_total_cycles')
    guard['adc_preemption_contributor']=False
    result['actual_ccr']['possible_mixed_latch_count']=result['actual_ccr'].pop(
        'possible_suppressed_uev_count')
    result['actual_ccr']['target']='bottom following this ADC entry, previous accepted command'
    result['actual_ccr']['timer_update_modified_by_probe']=False
    result['pipeline']=dict(delay_cycles=1,delay_us=50,power_hard_off=True,
        generated=word('foc_pending_generated'),held=word('foc_pending_held'),
        empty=word('foc_pending_empty'),
        commit_max_cycles=word('foc_pending_commit_max_cycles'),
        generation_max_cycles=word('foc_pending_generation_max_cycles'),
        tim7_preempt_max_cycles=word('foc_tim7_preempt_max_cycles'))
    result['pipeline']['commit_max_us']=result['pipeline']['commit_max_cycles']/170
    result['pipeline']['generation_max_us']=result['pipeline']['generation_max_cycles']/170
    return result

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--elf',type=Path,required=True)
    p.add_argument('--ram',type=Path,required=True)
    p.add_argument('--flash',type=Path,required=True)
    p.add_argument('--vtor',type=lambda x:int(x,0),required=True)
    a=p.parse_args()
    print(json.dumps(decode(a.elf,a.ram.read_bytes(),a.flash.read_bytes(),a.vtor),indent=2))

if __name__=='__main__': main()
