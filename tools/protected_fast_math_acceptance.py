"""One bounded-trig compute trial; preserve 50 us wall budget and no motion."""
import protected_fast_math_stage as profile
import protected_irq_timing_acceptance as acceptance
from protected_irq_priority_fix_acceptance import validate_encoder

def validate_cost(row):
    cost=row.get('cost') or {}
    if cost.get('TRIG')!='POLY9_8' or cost.get('DWT')!='1':
        raise RuntimeError('Exact bounded-trig cost diagnostic absent')
    for key in ('CPU_MAX_CYC','PREEMPT_MAX_CYC','PAIR_MAX_US','MATH_MAX_US'):
        if key not in cost or not 0<=int(cost[key])<=0xffffffff:
            raise RuntimeError('Cost counter missing/invalid: '+key)
    if int(cost['CPU_MAX_CYC'])==0 or int(cost['MATH_MAX_US'])==0:
        raise RuntimeError('No observed FOC cost')
    # Never replace wall budget checks by subtraction of measured IRQ time.

def main():
    base_validate=acceptance.validate_sample
    def validate(row):
        base_validate(row); validate_encoder(row); validate_cost(row)
    acceptance.profile=profile
    acceptance.validate_sample=validate
    acceptance.main()

if __name__=='__main__': main()
