"""One pinned compact hard-off timing trial; 30s, strict 50us, no motion."""
import protected_irq_compact_stage as profile
import protected_adaptive_acceptance as adaptive
from protected_adaptive_ram_acceptance import validate_ram
from firmware_transfer_iap import fields

def validate_compact(row):
    validate_ram(row)
    if any(row.get('compact',{}).get(k)!=v for k,v in
        (('ENABLED','1'),('HARD_OFF','1'),('FIXED_OPS','1'),('GUARD_US','25'),('DEADLINE_US','50'))):
        raise RuntimeError('Compact fixed-ops identity/guardian/deadline absent')

def main():
    capture=adaptive.capture_adaptive
    validate=adaptive.validate_adaptive
    def read(uart,row):
        row=capture(uart,row)
        row['ram']=fields(uart.query('MOTOR TEST RAM'))
        row['compact']=fields(uart.query('MOTOR TEST COMPACT'))
        return row
    def check(row,*args):
        validate(row,*args); validate_compact(row)
    adaptive.AdaptiveConsole.READ|=frozenset(('MOTOR TEST RAM','MOTOR TEST COMPACT'))
    adaptive.capture_adaptive=read
    adaptive.validate_adaptive=check
    adaptive.main(profile,segment_limit='OFF',total_limit='OFF')

if __name__=='__main__': main()
