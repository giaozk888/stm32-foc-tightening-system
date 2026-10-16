"""Read-only locked fallback proof after one failed unconfirmed compact trial."""
import protected_irq_compact_stage as profile
import protected_adaptive_rollback as rollback
if __name__=='__main__': rollback.main(profile)
