"""One pinned adaptive compute-only trial; hard-off, no motor commands/retry."""
import protected_adaptive_stage as profile
import protected_irq_timing_acceptance as acceptance
from firmware_transfer_iap import fields
from protected_pair_fast_acceptance import validate_late
from protected_fast_math_acceptance import validate_cost
from protected_irq_priority_fix_acceptance import validate_encoder

class AdaptiveConsole(acceptance.TimingConsole):
    READ=acceptance.TimingConsole.READ|frozenset(('MOTOR TEST FILTER','MOTOR TEST ZERO ROBUST'))

def capture_adaptive(uart,row):
    row['adaptive']=fields(uart.query('MOTOR TEST FILTER'))
    row['robust_zero']=fields(uart.query('MOTOR TEST ZERO ROBUST'))
    return row

def validate_adaptive(row,segment_limit='3',total_limit='20'):
    a,z=row['adaptive'],row['robust_zero']
    if any(a.get(k)!=v for k,v in (('ADAPT','1'),('HARD_OFF','1'),('DELAY_PAIRS','1'))):
        raise RuntimeError('Hard-off adaptive profile absent')
    for key,low,high in (('JUMP',20,40),('NOISE_Q8',256,2048),('LEARNED',0,0xffffffff)):
        values=a.get(key,'').split(',')
        if len(values)!=2 or any(not v.isdigit() or not low<=int(v)<=high for v in values):
            raise RuntimeError('Adaptive bounds invalid: '+key)
    if (any(z.get(k)!=v for k,v in (('BLOCK','5'),('SEGMENT','500'),('SEGMENTS','8'),
            ('MAX',total_limit),('SEG_MAX',segment_limit),('FLAGS','0'),('HARD_OFF','1'))) or
        not z.get('OUTLIERS','').isdigit() or
        not 0<=int(z['OUTLIERS'])<=(800 if total_limit=='OFF' else 20)):
        raise RuntimeError('Robust zero incomplete or unhealthy')
    if segment_limit=='OFF' and z.get('SEG_OUTLIERS')!='0':
        raise RuntimeError('Completed zero must have closed its last diagnostic segment')

def main(config=None,segment_limit='3',total_limit='20'):
    base_read=acceptance.read_sample
    base_validate=acceptance.validate_sample
    def read(uart): return capture_adaptive(uart,base_read(uart))
    def validate(row):
        base_validate(row); validate_encoder(row); validate_cost(row); validate_late(row)
        validate_adaptive(row,segment_limit,total_limit)
    acceptance.profile=config or profile
    acceptance.TimingConsole=AdaptiveConsole
    acceptance.read_sample=read
    acceptance.validate_sample=validate
    acceptance.main()

if __name__=='__main__': main()
