"""One compute-only IRQ-source trial; evidence retained before validation."""
import protected_irq_source_stage as profile
import protected_irq_timing_acceptance as acceptance
from firmware_transfer_iap import fields
from protected_pair_fast_acceptance import validate_late
from protected_fast_math_acceptance import validate_cost
from protected_irq_priority_fix_acceptance import validate_encoder

class SourceConsole(acceptance.TimingConsole):
    READ=acceptance.TimingConsole.READ|frozenset(('MOTOR TEST IRQ','MOTOR TEST IRQ STATS','MOTOR TEST IRQ TOTAL'))

def capture_sources(uart,row):
    for key,cmd in (('irq_frame','MOTOR TEST IRQ'),('irq_stats','MOTOR TEST IRQ STATS'),
                    ('irq_total','MOTOR TEST IRQ TOTAL')):
        row[key]=fields(uart.query(cmd))
    return row

def validate_sources(row):
    for key in ('irq_frame','irq_stats','irq_total'):
        if row[key].get('ERR')!='0' or row[key].get('ORDER')!='G,T,R,X':
            raise RuntimeError('IRQ source hook evidence invalid')
    if row['irq_frame'].get('VALID')!='0':
        raise RuntimeError('First-late frame present; wall budget not passed')
    if row['irq_frame'].get('BODY')!='EXCL' or row['irq_total'].get('BODY')!='EXCL' or row['irq_stats'].get('MAX')!='BODY_INCL':
        raise RuntimeError('IRQ source scope mismatch')
    for key,name in (('irq_stats','CNT'),('irq_stats','MAX_CYC'),('irq_total','CYC')):
        parts=row[key].get(name,'').split(',')
        if len(parts)!=4 or any(not x.isdigit() for x in parts):
            raise RuntimeError('Incomplete IRQ source fields')
    if int(row['irq_stats']['CNT'].split(',')[0])<1000:
        raise RuntimeError('Guardian source evidence insufficient')

def main():
    base_read=acceptance.read_sample
    base_validate=acceptance.validate_sample
    def read(uart): return capture_sources(uart,base_read(uart))
    def validate(row):
        base_validate(row); validate_encoder(row); validate_cost(row); validate_late(row); validate_sources(row)
    acceptance.profile=profile
    acceptance.TimingConsole=SourceConsole
    acceptance.read_sample=read
    acceptance.validate_sample=validate
    acceptance.main()

if __name__=='__main__': main()
