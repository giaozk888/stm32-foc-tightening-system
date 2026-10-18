/* Execute the real IRQ wrapper and real feedback/safety core, with an
 * intentionally state-changing PI/PWM stub to detect any invalid-path call. */
#define main legacy_irq_cases_not_run
#include "protected_adc_irq_host.c"
#undef main
static void setup(uint16_t zero_u,uint16_t zero_v)
{
    reset(); cl_armed=1U; pwm_writes=0U;
    command_d=.31f; command_q=-.29f;
    encoder_theta_e_pred=.5f; encoder_omega_e_rad_s=10.0f;
    foc_int_d_V=.75f; foc_int_q_V=-.75f;
    cl_session.state=CL_RUNNING;
    FocFeedbackSafetyConfig cfg={ .protection={4.0f,100U,100U,6U,4U},
        .zero_u=zero_u,.zero_v=zero_v,.count_to_A=3300.0f/(4095.0f*120.0f) };
    assert(FocFeedbackSafety_Begin(&fast_safety,cfg,100U)==FOC_OC_CLEAR);
}
int main(void)
{
    setup(1111,2222); ProtectedLoop_AdcIrq();
    assert(math_calls==1U && pwm_writes==1U && cl_current_path==1U);
    assert(foc_int_d_V==.875f && foc_int_q_V==-.875f);
    for (unsigned state=CL_READY;state<=CL_RUNNING;++state) {
        setup(1200,2222); cl_session.state=state;
        ProtectedLoop_AdcIrq();
        assert(!math_calls && !pwm_writes && !ended && !fault && cl_current_path==2U);
        assert(command_d==.31f && command_q==-.29f);
        assert(foc_int_d_V==.75f && foc_int_q_V==-.75f);
        assert(encoder_theta_e_pred>.5f); /* Time, not PI, still advances. */
    }
    /* Case C also exits before the state-changing PI/PWM stub. */
    setup(1200,2222);
    fast_safety.validation.state=FOC_CURRENT_SUSPECT;
    fast_safety.validation.candidate=(CurrentRawPair){1500,2222};
    ProtectedLoop_AdcIrq();
    assert(!math_calls && !pwm_writes && !fault && cl_current_path==FOC_CURRENT_PATH_UNRESOLVED);
    assert(command_d==.31f && command_q==-.29f);
    assert(foc_int_d_V==.75f && foc_int_q_V==-.75f && encoder_theta_e_pred>.5f);
    /* Same physical pair becomes usable once the next event confirms the
     * new candidate: normal math resumes, not a second stale-ref rejection. */
    setup(1200,2222);
    fast_safety.validation.state=FOC_CURRENT_SUSPECT;
    fast_safety.validation.candidate=(CurrentRawPair){1110,2222};
    ProtectedLoop_AdcIrq();
    assert(math_calls==1U && pwm_writes==1U && !fault && cl_current_path==FOC_CURRENT_PATH_NORMAL);
    assert(fast_safety.validation.current_confirmed_transition==1U);
    assert(fast_safety.validation.reference.u==1111U && fast_safety.validation.reference.v==2222U);
    setup(1200,2222);
    fast_safety.validation.state=FOC_CURRENT_SUSPECT;
    fast_safety.validation.candidate=(CurrentRawPair){1500,2222};
    fast_safety.validation.current_unresolved_consecutive=2U;
    ProtectedLoop_AdcIrq();
    assert(fault && !power && !cl_armed && !pwm_writes && !math_calls);
    assert(fast_safety.protection.reason==FOC_FP_CURRENT_INVALID);
    setup(1800,2222); fast_safety.protection.pending=1U;
    fast_safety.protection.pending_us=100U;
    fast_safety.protection.confirm_cycles=CUR_CONFIRM_MAX_CYCLES-1U;
    ProtectedLoop_AdcIrq();
    assert(fault && !power && !pwm_writes && !math_calls);
    assert(fast_safety.protection.reason==FOC_FP_TIMEOUT);
    assert(fast_safety.protection.timeout.reason==FOC_TO_CURRENT_CONFIRM);
    assert(fast_safety.protection.cur_confirm_fault_count==1U);
    puts("PASS actual ADC IRQ: suspect/unresolved freeze PI, integrators, voltage and PWM; unresolved/raw OC closes power");
    return 0;
}
