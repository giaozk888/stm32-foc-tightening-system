"""One compute-only trial of the pinned DMA fault-snapshot B image.

Shares the existing no-motion, no-retry, normal boot-confirmation acceptance
path.  It never issues a motor-start command.
"""
import protected_irq_dma_trace_stage as trace
import protected_irq_timing_acceptance as acceptance

if __name__=='__main__':
    acceptance.profile=trace
    acceptance.main()
