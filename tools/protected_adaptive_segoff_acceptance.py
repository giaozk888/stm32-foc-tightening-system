"""One SEG_MAX=OFF hard-off trial, keeping the same sub-50-us criteria."""
import protected_adaptive_segoff_stage as profile
import protected_adaptive_acceptance as acceptance
if __name__=='__main__': acceptance.main(profile,segment_limit='OFF')
