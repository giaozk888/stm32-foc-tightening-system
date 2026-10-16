"""One hard-off SRAM trial, 30 seconds observed; strict 50 us, no motor."""
import protected_adaptive_ram_stage as profile
import protected_adaptive_acceptance as adaptive
from firmware_transfer_iap import fields

def validate_ram(row):
    if any(row.get('ram',{}).get(k)!=v for k,v in
        (('ENABLED','1'),('HARD_OFF','1'),('DEADLINE_US','50'))):
        raise RuntimeError('RAM candidate identity or unchanged timing limit absent')

def main():
    capture=adaptive.capture_adaptive
    validate=adaptive.validate_adaptive
    def read(uart,row):
        row=capture(uart,row)
        row['ram']=fields(uart.query('MOTOR TEST RAM'))
        return row
    def check(row,*args):
        validate(row,*args); validate_ram(row)
    adaptive.AdaptiveConsole.READ|=frozenset(('MOTOR TEST RAM',))
    adaptive.capture_adaptive=read
    adaptive.validate_adaptive=check
    adaptive.main(profile,segment_limit='OFF',total_limit='OFF')

if __name__=='__main__': main()
