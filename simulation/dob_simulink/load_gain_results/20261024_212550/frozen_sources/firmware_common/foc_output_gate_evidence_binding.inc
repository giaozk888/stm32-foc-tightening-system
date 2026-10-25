/* Independent opt-in A diagnostic, no gate writes, timers or protection edits.
 * Read-only on the good path; only a failed predicate writes a bounded binary
 * record. No formatting/UART/HAL, and no additional IRQ masking on success. */
#include "foc_output_gate_evidence.h"
#if !defined(FOC_CURRENT_STEP_AB_DIAG) || !defined(FOC_PROTECTED_CLOSED_LOOP)
#error Gate evidence is restricted to the protected manual current-step A image
#endif
static volatile FocOutputGateEvidence cl_output_gate_evidence;
static inline uint32_t GateEvidence_StateRead(void)
{
    /* Do not let GCC merge the before/used/after reads of the non-volatile
     * session object. This is an observer-only volatile view, not a change
     * to session ownership or control synchronization. */
    return *(const volatile __typeof__(cl_session.state) *)&cl_session.state;
}

/* Keep the call boundary so LR resolves to the actual gate-check caller in
 * the ELF (ADC, guardian or pending-commit permit), not to a shared latch. */
__attribute__((noinline,optimize("O2")))
static uint8_t ProtectedLoop_GatesObserved(void)
{
    const uint32_t seq_before=injected_seq_count, state_before=GateEvidence_StateRead();
    const uint32_t odr=DRIVER_SD_GPIO_Port->ODR;
    const uint32_t bdtr_moe=TIM1->BDTR;
    const uint32_t cr1=TIM1->CR1, bdtr_aoe=TIM1->BDTR;
    const uint32_t state_used=GateEvidence_StateRead(), ccer=TIM1->CCER;
    const uint32_t bad=FocOutputGate_Mismatch(state_used==CL_RUNNING,
        cr1 & TIM_CR1_CEN,bdtr_aoe & TIM_BDTR_AOE,
        odr & DRIVER_SD_Pin,bdtr_moe & TIM_BDTR_MOE,ccer);
    if (bad && cl_armed && !cl_output_gate_evidence.valid) {
        /* Serialize only the first failure. PRIMASK is restored exactly;
         * preempting readers cannot publish/overwrite a partial first record.
         * The existing caller still faults on this very same failed check. */
        const uint32_t mask=__get_PRIMASK(); __disable_irq();
        if (!cl_output_gate_evidence.valid) {
            cl_output_gate_evidence.version=1U;
            cl_output_gate_evidence.mismatch=bad;
            cl_output_gate_evidence.caller_pc=(uint32_t)(uintptr_t)__builtin_return_address(0);
            cl_output_gate_evidence.ipsr=__get_IPSR();
            cl_output_gate_evidence.dwt=DWT->CYCCNT;
            cl_output_gate_evidence.timer_us=AS5047P_DmaNowUs();
            cl_output_gate_evidence.seq_before=seq_before;
            cl_output_gate_evidence.seq_after=injected_seq_count;
            cl_output_gate_evidence.state_before=state_before;
            cl_output_gate_evidence.state_used=state_used;
            cl_output_gate_evidence.state_after=GateEvidence_StateRead();
            cl_output_gate_evidence.odr=odr;
            cl_output_gate_evidence.bdtr_moe_read=bdtr_moe;
            cl_output_gate_evidence.cr1=cr1;
            cl_output_gate_evidence.bdtr_aoe_read=bdtr_aoe;
            cl_output_gate_evidence.ccer=ccer;
            cl_output_gate_evidence.sr=TIM1->SR;
            cl_output_gate_evidence.primask=mask;
            cl_output_gate_evidence.armed=cl_armed;
            __DMB(); cl_output_gate_evidence.valid=1U; __DMB();
        }
        __set_PRIMASK(mask);
    }
    return bad==0U;
}
