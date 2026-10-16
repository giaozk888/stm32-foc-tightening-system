"""Read-only locked fallback proof after a single failed RAM trial."""
import protected_adaptive_ram_stage as profile
import protected_adaptive_rollback as rollback
if __name__=='__main__': rollback.main(profile)
