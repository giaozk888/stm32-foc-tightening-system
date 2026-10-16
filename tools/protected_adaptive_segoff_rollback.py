"""Read-only automatic fallback proof for the single segment-off trial."""
import protected_adaptive_segoff_stage as profile
import protected_adaptive_rollback as rollback
if __name__=='__main__': rollback.main(profile)
