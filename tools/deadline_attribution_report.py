"""Offline decoder for the new frozen deadline schema. No device access."""
import argparse
import json
import struct
import pwm_pipeline_report as pipeline

FIELDS=('captured','valid','wall_cycles','active_est_cycles','tim2_cycles',
        'tim2_count','dma_rx_cycles','dma_rx_count','other_irq_cycles',
        'other_irq_count','preempt_total_cycles','tim1_cnt','tim1_dir',
        'dwt_entry','dwt_exit','timer_span')

def decode(elf,ram,flash,vtor):
    result=pipeline.decode(elf,ram,flash,vtor)
    symbols=pipeline.base.schema.symbols(elf)
    addr,size=symbols['deadline_snapshot']
    off=addr-0x20000000
    if size!=64 or not 0<=off<=len(ram)-64:
        raise ValueError('Unexpected deadline snapshot layout')
    d=dict(zip(FIELDS,struct.unpack_from('<16I',ram,off)))
    if d['valid'] and (not d['captured'] or
        d['wall_cycles']!=d['active_est_cycles']+d['preempt_total_cycles'] or
        d['preempt_total_cycles']!=d['tim2_cycles']+d['dma_rx_cycles']+d['other_irq_cycles'] or
        (d['dwt_exit']-d['dwt_entry'])&0xffffffff!=d['wall_cycles']):
        raise ValueError('Incoherent deadline snapshot: not usable attribution')
    d['status']='VALID_FIRST_MISS' if d['valid'] else (
        'CAPTURED_BUT_UNTRUSTED' if d['captured'] else 'NO_SNAPSHOT')
    for key in ('wall_cycles','active_est_cycles','tim2_cycles','dma_rx_cycles',
                'other_irq_cycles','preempt_total_cycles','timer_span'):
        d[key.removesuffix('_cycles')+'_us']=d[key]/170
    result['deadline_snapshot']=d
    return result

def main():
    from pathlib import Path
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--elf',type=Path,required=True)
    p.add_argument('--ram',type=Path,required=True)
    p.add_argument('--flash',type=Path,required=True)
    p.add_argument('--vtor',type=lambda x:int(x,0),required=True)
    a=p.parse_args()
    print(json.dumps(decode(a.elf,a.ram.read_bytes(),a.flash.read_bytes(),a.vtor),indent=2))

if __name__=='__main__': main()
