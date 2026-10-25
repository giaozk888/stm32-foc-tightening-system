#ifndef FOC_OUTPUT_GATE_EVIDENCE_H
#define FOC_OUTPUT_GATE_EVIDENCE_H
#include <stdint.h>

/* Diagnostic bits, NOT new protection thresholds or an alternative admission. */
enum {
    FOC_GATE_CEN_OFF=1U, FOC_GATE_AOE_ON=2U, FOC_GATE_SD=4U,
    FOC_GATE_MOE=8U, FOC_GATE_CCER=16U
};
static inline uint32_t FocOutputGate_Mismatch(uint32_t running,uint32_t cen,
    uint32_t aoe,uint32_t sd,uint32_t moe,uint32_t ccer)
{
    return (!cen ? FOC_GATE_CEN_OFF : 0U) | (aoe ? FOC_GATE_AOE_ON : 0U) |
        ((!!sd != !!running) ? FOC_GATE_SD : 0U) |
        ((!!moe != !!running) ? FOC_GATE_MOE : 0U) |
        ((ccer != (running ? 0x555U : 0U)) ? FOC_GATE_CCER : 0U);
}

/* All uint32_t, versioned stopped-SRAM ABI. Predicate inputs are the original
 * read values, not values re-read after EmergencyOff. Before/after tokens
 * expose an observation interrupted by an ADC/session transition; do not
 * misrepresent non-atomic peripheral reads as a simultaneous hardware sample.
 * valid is written LAST with a DMB, first record retained until reset. */
typedef struct {
    uint32_t valid, version, mismatch, caller_pc, ipsr, dwt, timer_us;
    uint32_t seq_before, seq_after, state_before, state_used, state_after;
    uint32_t odr, bdtr_moe_read, cr1, bdtr_aoe_read, ccer, sr, primask, armed;
} FocOutputGateEvidence;
#endif
