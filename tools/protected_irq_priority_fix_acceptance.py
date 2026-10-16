"""One priority-fix compute-only trial; no motor commands or timeout bypass."""
import protected_irq_priority_fix_stage as profile
import protected_irq_timing_acceptance as acceptance

def validate_encoder(row):
    dma=row.get('encoder_dma') or {}
    irq=row.get('encoder_irq') or {}
    snapshot=row.get('encoder_snapshot') or {}
    if (any(dma.get(k)!='0' for k in ('FAIL','TIMEOUT','IO','SCHED','STALE')) or
        int(dma.get('READS','0'))<100 or snapshot.get('VALID')!='0' or
        irq.get('VALID')!='0' or not 0<=int(irq.get('MAX_LATE_US','200'))<200):
        raise RuntimeError('Encoder/guard evidence failed for priority fix')

def main():
    base_validate=acceptance.validate_sample
    def validate(row):
        base_validate(row)
        validate_encoder(row)
    acceptance.profile=profile
    acceptance.validate_sample=validate
    acceptance.main()

if __name__=='__main__': main()
