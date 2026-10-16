"""Read-only fallback proof after the single no-quota trial fails."""
import protected_adaptive_noquota_stage as profile
import protected_adaptive_rollback as rollback

if __name__=='__main__': rollback.main(profile)
