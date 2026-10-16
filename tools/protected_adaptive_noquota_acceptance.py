"""One hard-off no-zero-quota compute trial; retain sub-50-us criteria."""
import protected_adaptive_noquota_stage as profile
import protected_adaptive_acceptance as acceptance

if __name__=='__main__': acceptance.main(profile,segment_limit='OFF',total_limit='OFF')
