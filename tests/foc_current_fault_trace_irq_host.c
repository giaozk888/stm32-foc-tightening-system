/* Run the real IRQ/core regression with diagnostics enabled, then prove a
 * protection-return frame cannot inherit the preceding discriminator result. */
#define main previous_irq_tests
#include "protected_adc_irq_host.c"
#undef main
int main(void)
{
    foc_current_fault_trace=(FocCurrentTrace){0}; foc_current_trace_frame=0;
    reset(); cl_armed=1U; pwm_writes=0U;
    cl_session.state=CL_RUNNING;
    FocFeedbackSafetyConfig cfg={ .protection={4.0f,100U,100U,6U,4U},
        .zero_u=1800,.zero_v=2222,.count_to_A=3300.0f/(4095.0f*120.0f) };
    assert(FocFeedbackSafety_Begin(&fast_safety,cfg,100U)==FOC_OC_CLEAR);
    fast_safety.protection.pending=1U;
    fast_safety.protection.pending_us=100U;
    fast_safety.protection.confirm_cycles=CUR_CONFIRM_MAX_CYCLES-1U;
    fast_safety.validation.state=FOC_CURRENT_TRACKING;
    ProtectedLoop_AdcIrq();
    FocCurrentTraceFrame *f=&foc_current_fault_trace.frames[0];
    assert(fault && !power && !pwm_writes && !math_calls);
    assert(!foc_current_fault_trace.frozen && f->protection_fault);
    assert(f->over_mask==5U && f->confirm_cycles==4U); /* U and reconstructed W. */
    assert(!f->discriminator_executed && f->discriminator_result==-2);
    assert(f->pi_frozen && f->pwm_frozen);
    /* Same production IRQ/core path, but now the actual discriminator latches
     * CURRENT_INVALID. Context must precede its candidate overwrite. */
    foc_current_fault_trace=(FocCurrentTrace){0}; foc_current_trace_frame=0;
    reset(); cl_armed=1U; pwm_writes=0U;
    cl_session.state=CL_RUNNING;
    assert(FocFeedbackSafety_Begin(&fast_safety,cfg,100U)==FOC_OC_CLEAR);
    fast_safety.validation.state=FOC_CURRENT_SUSPECT;
    fast_safety.validation.candidate=(CurrentRawPair){2500U,2222U};
    fast_safety.validation.current_unresolved_consecutive=2U;
    ProtectedLoop_AdcIrq();
    f=&foc_current_fault_trace.frames[0];
    assert(fault && !power && !pwm_writes && !math_calls);
    assert(foc_current_fault_trace.frozen && f->protection_reason==FOC_FP_CURRENT_INVALID);
    assert(f->discriminator_executed && f->discriminator_result==-1);
    assert(f->reference_u_before==1800U && f->candidate_u_before==2500U);
    assert(f->d_old==689U && f->d_candidate==1389U);
    assert(f->unresolved_consecutive_before==2U && fast_safety.validation.candidate.u==1111U);
    puts("PASS actual IRQ trace: early return captured, output closure unchanged");
    return 0;
}
