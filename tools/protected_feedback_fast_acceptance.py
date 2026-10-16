"""One pinned feedback-inline compute-only trial; retain original wall budget."""
import protected_feedback_fast_stage as profile
import protected_irq_timing_acceptance as acceptance
from protected_pair_fast_acceptance import validate_late
from protected_fast_math_acceptance import validate_cost
from protected_irq_priority_fix_acceptance import validate_encoder


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


if __name__=='__main__': main()
