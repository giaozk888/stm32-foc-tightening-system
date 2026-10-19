/* Adapter only: no recipe rewrite and no duplicate tightening state machine.
 * Local START remains the producer, original TighteningTask the consumer.
 * The selected profile supplies the one-shot lease; 20 rpm admission stays. */
static uint8_t LatestOriginal_RecipeReady(void)
{
#if defined(FOC_TORQUE_CHAIN_DIAG)
    return torque_diag.admitting; /* No recipe mutation; manual IQ owner only. */
#else
#if defined(FOC_LOADED_FSM_TRIAL)
    /* Refuse a recipe that cannot finish within this profile's lease.
     * Existing FSM stop-settle timeout is 2000 ms; reserve 300 ms for its
     * 100 Hz transitions. Never shorten or rewrite a loaded recipe here. */
    uint32_t post_ms=recipe_state.params.seating_ms+recipe_state.params.t1_ms+
        recipe_state.params.t2_ms+recipe_state.params.t3_ms+recipe_state.params.hold_ms;
    if (recipe_state.params.rundown_timeout_ms>8000U || post_ms>1700U)
        return 0U;
#endif
    return recipe_state.params.rundown_rpm > 0U &&
        recipe_state.params.rundown_rpm <= CL_SPEED_RPM;
#endif
}
static uint8_t LatestOriginal_Ready(void)
{
#if defined(FOC_TORQUE_CHAIN_DIAG)
    if (tightening_stop_request || tightening_start_request ||
        !torque_diag.queued || !torque_diag.prepared) return 0U;
#endif
    return !analog_safe_latched && LatestOriginal_RecipeReady() && ProtectedLoop_Ready() &&
        (uint32_t)(AS5047P_DmaNowUs()-cl_session.outer_us)<=CL_OUTER_DEADLINE_US;
}
static uint8_t LatestOriginal_Admit(void)
{
#if defined(FOC_TORQUE_CHAIN_DIAG)
    if (!torque_diag.admitting) return 0U; /* Refuse ordinary START/RPC. */
#if defined(FOC_BREAKAWAY_CURRENT_TEST)
    if (!FocBreakaway_WithinLimit(torque_diag.iq_mA,
            (uint16_t)(MOTOR_DIRECT_IQ_LIMIT_A*1000.0f+0.5f)) ||
        (torque_diag.sign!=1 && torque_diag.sign!=-1) || torque_diag.offset_deg!=0)
        return 0U;
#endif
#endif
#if defined(FOC_RC_DEFERRED_SHADOW) || defined(FOC_FAST_REJECT_COMPUTE_ONLY)
    /* This observer must have no compiled bridge-enable transaction. */
    return 0U;
#else
    FocWindowPlan plan;
    FocWindowStatus status=FocAdcTiming_Prepare(0.5f,0.5f,0.5f,&plan);
    uint32_t mask=__get_PRIMASK(); __disable_irq();
    uint8_t healthy=LatestOriginal_Ready() && FocAdcTiming_FastCanStart();
    if (status!=FOC_WINDOW_OK || !healthy ||
        !ClSession_Queue(&cl_session,healthy) ||
        !ClSession_Start(&cl_session,AS5047P_DmaNowUs(),healthy)) {
        if (status!=FOC_WINDOW_OK) FocAdcTiming_PlanFailed(status);
        __set_PRIMASK(mask);
        return 0U;
    }
#if defined(FOC_PWM_PIPELINE_CLOSED_LOOP)
    /* READY has committed ONLY neutral for >=1000 ADC entries. Those active
     * compares are already latched. Do not make a task-context CCR/UDIS write
     * or expose an old READY shadow command during this enable transaction. */
    ProtectedLoop_PwmInvalidate();
#else
    FocAdcTiming_CommitPrepared(&plan);
#endif
    /* Drop shadow-integrator memory before the sole power-enable transaction.
     * The original FSM sets its speed/Iq immediately after this admission. */
    FocCurrentPi_Reset(&foc_int_d_V,&foc_int_q_V);
    foc_id_ref_A=foc_iq_ref_A=foc_vd_V=foc_vq_V=0.0f;
#if defined(FOC_TORQUE_CHAIN_DIAG)
#if defined(FOC_SPEED_DYNAMIC_DIAG)
    /* The unchanged 1kHz SPEED PI generates Iq; no fixed-current stages. */
    MotorControl_SetSpeed((float)CL_SPEED_RPM);
#else
    /* IQ mode BEFORE gates ON; no speed PI; IdRef remains exactly zero. */
#if defined(FOC_BREAKAWAY_CURRENT_TEST)
    MotorControl_SetIq((float)torque_diag.sign*(float)torque_diag.iq_mA*0.001f);
#else
    MotorControl_SetIq((float)torque_diag.sign*FOC_TORQUE_CHAIN_IQ_A);
#endif
#endif
    torque_diag.active=1U;
#endif
#if defined(FOC_STARTUP_TRACE)
    FocStartup_Begin(&cl_startup,cl_session.start_us);
#endif
    TIM1->CCER=0x555U; TIM1->BDTR=(TIM1->BDTR & ~TIM_BDTR_AOE)|TIM_BDTR_MOE;
    DRIVER_SD_GPIO_Port->BSRR=DRIVER_SD_Pin; __DSB();
    __set_PRIMASK(mask);
    return 1U;
#endif
}
static void LatestOriginal_FsmService(void)
{
#if defined(FOC_TORQUE_CHAIN_DIAG)
    if (torque_diag.active && cl_session.state==CL_RUNNING) return;
#endif
    /* Called AFTER the original FSM transition. CONTACT_STOP may be IDLE but
     * remains busy: do not mistake that deliberate pause for cycle completion. */
    if (cl_session.state==CL_RUNNING && !Tightening_IsBusy()) ProtectedLoop_Stop();
}
#if defined(FOC_TORQUE_CHAIN_DIAG)
#include "foc_torque_chain_binding.inc"
#endif
