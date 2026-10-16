"""Single pair-fast compute trial; no motor command or relaxed wall budget."""
import protected_pair_fast_stage as profile
import protected_irq_timing_acceptance as acceptance
from protected_fast_math_acceptance import validate_cost
from protected_irq_priority_fix_acceptance import validate_encoder


def validate_late(row):
    late=row.get('late_frame') or {}
    if late.get('PATH')!='PAIR2' or late.get('VALID')!='0':
        raise RuntimeError('Pair-fast path missing or first-late frame recorded')
    for key in ('SEQ','US','PAIR_US','MATH_US','WALL_CYC','IRQ_CYC'):
        if key not in late or not 0<=int(late[key])<=0xffffffff:
            raise RuntimeError('First-late frame diagnostic missing/invalid: '+key)


def main():
    base_validate=acceptance.validate_sample
    def validate(row):
        base_validate(row)
        validate_encoder(row)
        validate_cost(row)
        validate_late(row)
    acceptance.profile=profile
    acceptance.validate_sample=validate
    acceptance.main()


if __name__=='__main__':
    main()
