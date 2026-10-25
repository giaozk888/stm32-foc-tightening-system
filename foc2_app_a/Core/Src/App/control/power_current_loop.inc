/* App A control/power_current_loop.inc: private binding, included once by main.c.
 * Keep the declared include order and original control/IRQ ownership. */
static uint8_t Router_Uart1Tx(const RouterPacket_t *packet)
{
    char frame[ROUTER_MAX_PAYLOAD + 96U];
    if (packet == NULL || packet->length > ROUTER_MAX_PAYLOAD) return 0U;
    if (g_rtos_started != 0U && g_uart_async_runtime_enable != 0U)
        return RouterUartTx_Queue(packet, UART_PROTOCOL_TX_TIMEOUT_MS);
    /* Pre-scheduler fallback remains synchronous and never uses the heap. */
    frame[0] = '\r'; frame[1] = '\n';
    size_t len = Router_EncodeAsciiFrame(packet, frame + 2U, sizeof(frame) - 2U);
    if (len == 0U || len + 4U >= sizeof(frame)) return 0U;
    len += 2U;
    frame[len++] = '\r'; frame[len++] = '\n'; frame[len] = '\0';
    return UART_SendReliableString(frame);
}


static void PowerStage_Disable(void)
{
    HAL_GPIO_WritePin(DRIVER_SD_GPIO_Port, DRIVER_SD_Pin, GPIO_PIN_RESET);
}

static void PowerStage_Enable(void)
{
#if defined(FOC_PROTECTED_CLOSED_LOOP)
    /* Only the bounded task-owned transaction in ProtectedLoop can enable. */
    PowerStage_Disable();
    return;
#endif
#if defined(ZERO_RETEST_BOOT)
    PowerStage_Disable();
    return;
#endif
#if defined(FOC_ISOLATED_CONCURRENCY)
    PowerStage_Disable();
    return;
#endif
#if defined(FOC_ADC_WINDOW)
    if (!FocAdcTiming_CanStart() || adc_fault != 0U)
    {
        PowerStage_Disable();
        __HAL_TIM_MOE_DISABLE(&htim1);
        return;
    }
#endif
#if defined(SAFETY_LOCKED_BOOT)
    /* Build-level gate: no software command can energize this profile. */
    PowerStage_Disable();
    return;
#else
    if (analog_safe_latched != 0U)
    {
        PowerStage_Disable();
        return;
    }
    HAL_GPIO_WritePin(DRIVER_SD_GPIO_Port, DRIVER_SD_Pin, GPIO_PIN_SET);
#endif
}

static void PWM_SetDuty(float du, float dv, float dw)
{
#if defined(FOC_PROTECTED_CLOSED_LOOP)
    ProtectedLoop_SetDuty(du,dv,dw);
    return;
#endif
#if defined(ZERO_RETEST_BOOT)
    (void)du; (void)dv; (void)dw;
    return;
#endif
#if defined(FOC_ISOLATED_CONCURRENCY)
    /* Compute-only acceptance: never publish FOC duties to timer outputs. */
    (void)du; (void)dv; (void)dw;
    return;
#endif
#if defined(FOC_ADC_WINDOW)
    if (FocAdcTiming_Commit(du, dv, dw) != FOC_WINDOW_OK)
    {
        adc_fault = 1U;
        foc_enable = 0U;
        foc_fault = 1U;
        foc_fault_reason = FOC_FAULT_ADC_WINDOW;
        DRIVER_SD_GPIO_Port->BSRR = (uint32_t)DRIVER_SD_Pin << 16U;
        TIM1->BDTR &= ~TIM_BDTR_MOE;
        __DSB();
        FaultDiag_Motor(FOC_FAULT_ADC_WINDOW);
    }
    return;
#else
    uint32_t u, v, w;

    if (du < 0.02f) du = 0.02f;
    if (du > 0.98f) du = 0.98f;
    if (dv < 0.02f) dv = 0.02f;
    if (dv > 0.98f) dv = 0.98f;
    if (dw < 0.02f) dw = 0.02f;
    if (dw > 0.98f) dw = 0.98f;

    u = (uint32_t)(du * (float)(PWM_ARR + 1U));
    v = (uint32_t)(dv * (float)(PWM_ARR + 1U));
    w = (uint32_t)(dw * (float)(PWM_ARR + 1U));

    if (u > PWM_ARR) u = PWM_ARR;
    if (v > PWM_ARR) v = PWM_ARR;
    if (w > PWM_ARR) w = PWM_ARR;

    __HAL_TIM_SET_COMPARE(&htim1, TIM_CHANNEL_1, u);
    __HAL_TIM_SET_COMPARE(&htim1, TIM_CHANNEL_2, v);
    __HAL_TIM_SET_COMPARE(&htim1, TIM_CHANNEL_3, w);
#endif
}

static float ClampFloat(float x, float lo, float hi)
{
    if (x < lo) return lo;
    if (x > hi) return hi;
    return x;
}

static void FOC_ResetController(void)
{
#if defined(FOC_BEMF_CANDIDATE)
    bemf_frame.valid=0U;
#endif
#if defined(FOC_DQ_DECOUPLING_CANDIDATE)
    dq_decoupling_frame.valid=0U;
#endif
#if defined(FOC_SPEED_BRAKE_TRACK)
    SpeedBrakeTrack_Reset(&speed_brake_track);
#endif
#if defined(FOC_ONE_CYCLE_PWM_PIPELINE)
    ProtectedLoop_PwmInvalidate();
#endif
    foc_id_ref_A = FOC_ID_REF_A;
    foc_iq_ref_A = 0.0f;

    encoder_position_deg = 0.0f;
    position_target_deg = 0.0f;
    position_error_deg = 0.0f;
    position_speed_cmd_rpm = 0.0f;
    position_deadband_active = 1U;
    active_hold_enable = 0U;
    active_hold_iq_cmd_A = 0.0f;
    position_error_sign_prev = 0;
    position_direction_reset_count = 0U;

    speed_target_rpm = SPEED_REF_RPM;
    speed_ref_rpm = SPEED_REF_RPM;
#if defined(FOC_SPEED_SCURVE_CANDIDATE)
    SpeedScurve_Reset(&speed_scurve, speed_ref_rpm);
#endif
#if defined(FOC_ACCEL_FEEDFORWARD_CANDIDATE)
    SpeedAccelFf_Reset();
#endif
    speed_integrator_A = 0.0f;
    speed_integrator_bleed_active = 0U;
    speed_overspeed_bleed_active = 0U;
    speed_error_rpm = 0.0f;
    speed_p_term_A = 0.0f;

    speed_diag_time_s = 0.0f;
    speed_diag_speed_integral = 0.0f;
    speed_diag_error_integral = 0.0f;
    speed_diag_min_rpm = 0.0f;
    speed_diag_max_rpm = 0.0f;
    speed_diag_valid = 0U;

    stall_timer_s = 0.0f;
    stall_trip_position_deg = 0.0f;
    stall_trip_target_deg = 0.0f;
    stall_trip_ref_rpm = 0.0f;
    stall_trip_speed_rpm = 0.0f;

    encoder_speed_rpm = 0.0f;
    encoder_omega_e_rad_s = 0.0f;

    encoder_rpm_instant = 0.0f;
    encoder_speed_detect_rpm = 0.0f;

    encoder_speed_dt_accum_s = 0.0f;
    encoder_speed_glitch_count = 0U;
    encoder_speed_glitch_streak = 0U;

    encoder_speed_detect_counts = 0;
    encoder_speed_detect_dt_s = 0.0f;
    encoder_speed_detect_samples = 0U;

    foc_id_A = 0.0f;
    foc_iq_A = 0.0f;
    foc_vd_V = 0.0f;
    foc_vq_V = 0.0f;

    foc_int_d_V = 0.0f;
    foc_int_q_V = 0.0f;

    foc_duty_u = 0.5f;
    foc_duty_v = 0.5f;
    foc_duty_w = 0.5f;

    PWM_SetDuty(0.5f, 0.5f, 0.5f);
}

/*
 * 20 kHz current-loop step.
 *
 * Coordinate convention:
 *   Clarke:
 *     Ialpha = IU
 *     Ibeta  = (IU + 2*IV)/sqrt(3)
 *
 *   Park:
 *     Id =  Ialpha*cos(theta_e) + Ibeta*sin(theta_e)
 *     Iq = -Ialpha*sin(theta_e) + Ibeta*cos(theta_e)
 *
 *   Inverse Park:
 *     Valpha = Vd*cos(theta_e) - Vq*sin(theta_e)
 *     Vbeta  = Vd*sin(theta_e) + Vq*cos(theta_e)
 *
 * Current polarity has already been verified in the previous test:
 *     positive current = ZERO_RAW - RAW
 */
FOC_HOT_PATH
static void FOC_CurrentLoopStep(uint16_t u_raw, uint16_t v_raw,
                                uint16_t u_physical, uint16_t v_physical)
{
    const float count_to_A =
        ((float)ADC_VREF_MV) /
        ((float)ADC_FULL_SCALE * (float)CURRENT_GAIN_MV_PER_A);

    float iu_A;
    float iv_A;
    float iw_A;
    float i_alpha;
    float i_beta;
    float theta;
    float s;
    float c;
    float id_A;
    float iq_A;
#if !defined(FOC_IDENT_VOLTAGE_STEP_DIAG)
    float err_d;
    float err_q;
#endif
    float vd;
    float vq;
#if !defined(FOC_IDENT_VOLTAGE_STEP_DIAG)
    float mag2;
    float limit2;
#endif
    float v_alpha;
    float v_beta;
    float vu;
    float vv;
    float vw;
    float vmax;
    float vmin;
    float voffset;
    float du;
    float dv;
    float dw;

#if defined(FOC_ISOLATED_CONCURRENCY)
    if (!IsolatedBench_Active() || encoder_valid == 0U)
#else
    if ((foc_enable == 0U) || (encoder_valid == 0U))
#endif
    {
        PWM_SetDuty(0.5f, 0.5f, 0.5f);
        return;
    }

#if defined(FOC_PROTECTED_CLOSED_LOOP)
    (void)count_to_A; (void)u_raw; (void)v_raw; (void)u_physical; (void)v_physical;
    iu_A=cl_frame.iu_A; iv_A=cl_frame.iv_A; iw_A=cl_frame.iw_A;
    (void)iw_A;
#elif defined(FOC_FEEDBACK_SAFETY_BINDING)
    /* The ADC binding already checked, selected and consumed this exact frame.
     * No legacy immediate amplitude gate in this hard-off candidate profile. */
    (void)count_to_A; (void)u_raw; (void)v_raw; (void)u_physical; (void)v_physical;
    iu_A = foc_feedback_control_frame.iu_A;
    iv_A = foc_feedback_control_frame.iv_A;
    iw_A = foc_feedback_control_frame.iw_A;
    (void)iw_A; /* Already reconstructed/checked by the guardian; Clarke uses U/V. */
#else
    iu_A = ((float)((int32_t)iu_zero_raw - (int32_t)u_raw)) * count_to_A;
    iv_A = ((float)((int32_t)iv_zero_raw - (int32_t)v_raw)) * count_to_A;
    iw_A = -(iu_A + iv_A);

#if defined(FOC_CURRENT_TREND4)
    /* Default policy: raw overload wins immediately at the unchanged limit.
     * The explicitly hard-off observation fixture keeps raw/feedback separate;
     * it cannot enable a physical power stage or qualify motor operation. */
    float filtered_u_A=iu_A, filtered_v_A=iv_A, filtered_w_A=iw_A;
    float physical_u_A = ((float)((int32_t)iu_zero_raw - u_physical)) * count_to_A;
    float physical_v_A = ((float)((int32_t)iv_zero_raw - v_physical)) * count_to_A;
    float physical_w_A = -(physical_u_A + physical_v_A);
    int physical_trip = FocTrend4_RawTrip(u_physical, v_physical,
        iu_zero_raw, iv_zero_raw, count_to_A, FOC_CURRENT_TRIP_A);
#if !defined(FOC_RAW_OBSERVE_ONLY)
    if (physical_trip) {
        iu_A = physical_u_A; iv_A = physical_v_A; iw_A = physical_w_A;
    }
#endif
#endif
    /*
     * Independent software phase-current trip, NOT an output-current command.
     * The requested 4 A threshold does not qualify the analog sensing chain
     * or resolve the previously observed fault at zero speed/torque command.
     */
    if (
#if defined(FOC_CURRENT_TREND4)
#if defined(FOC_RAW_OBSERVE_ONLY)
        /* Compile-time diagnostic ONLY: keep raw samples in the observer,
         * but never let a raw-only hit stop hard-off arithmetic. Invalid
         * data or a lost output lock still fail closed. Filtered overload
         * remains a stop unless separately opted into hard-off observation. */
        FocRawObserve_StopRequired(u_physical, v_physical, count_to_A,
            filtered_u_A, filtered_v_A, filtered_w_A, FOC_CURRENT_TRIP_A,
            IsolatedBench_Locked()) ||
#else
        physical_trip ||
#endif
#endif
#if defined(FOC_FILTERED_OBSERVE_ONLY)
        0 /* hard-off only; finite filtered overrange is observed below */
#else
        (fabsf(iu_A) > FOC_CURRENT_TRIP_A) ||
        (fabsf(iv_A) > FOC_CURRENT_TRIP_A) ||
        (fabsf(iw_A) > FOC_CURRENT_TRIP_A)
#endif
       )
    {
        foc_trip_iu_mA = (int32_t)(iu_A * 1000.0f);
        foc_trip_iv_mA = (int32_t)(iv_A * 1000.0f);
        foc_trip_iw_mA = (int32_t)(iw_A * 1000.0f);
        foc_fault_reason = 1U;
        foc_fault = 1U;
        foc_enable = 0U;
        HAL_GPIO_WritePin(DRIVER_SD_GPIO_Port,
                          DRIVER_SD_Pin,
                          GPIO_PIN_RESET);
        FaultDiag_Motor(1U);
        PWM_SetDuty(0.5f, 0.5f, 0.5f);

#if defined(FOC_CURRENT_TREND4)
        /* This stop is unconditional once its profile-specific gate fires.
         * Shadow classification never takes over the stop decision. */
        FocOcShadow_Push(&foc_oc_shadow, injected_seq_count,
            FocOcShadow_Mask(physical_u_A,physical_v_A,physical_w_A,FOC_CURRENT_TRIP_A),
            u_physical<=ADC_FULL_SCALE && v_physical<=ADC_FULL_SCALE);
#endif
        if (foc_current_trip_snapshot.valid == 0U)
        {
            uint32_t now_ms = HAL_GetTick();
            uint32_t vbus_age_ms = (analog_live_sample_count != 0U)
                                     ? (now_ms - analog_live_last_tick_ms)
                                     : UINT32_MAX;

            foc_current_trip_snapshot.tick_ms = now_ms;
            foc_current_trip_snapshot.adc_seq = injected_seq_count;
            foc_current_trip_snapshot.accepted_u = u_raw;
            foc_current_trip_snapshot.accepted_v = v_raw;
            foc_current_trip_snapshot.physical_u = u_physical;
            foc_current_trip_snapshot.physical_v = v_physical;
            foc_current_trip_snapshot.zero_u = iu_zero_raw;
            foc_current_trip_snapshot.zero_v = iv_zero_raw;
            foc_current_trip_snapshot.iu_mA = foc_trip_iu_mA;
            foc_current_trip_snapshot.iv_mA = foc_trip_iv_mA;
            foc_current_trip_snapshot.iw_mA = foc_trip_iw_mA;
            foc_current_trip_snapshot.filter_on = current_filter_enable;
            foc_current_trip_snapshot.median_count = current_med_count;
            foc_current_trip_snapshot.current_valid_count = current_valid_count;
            foc_current_trip_snapshot.current_reject_count = current_reject_count;
            foc_current_trip_snapshot.current_reject_streak = current_reject_streak;
            foc_current_trip_snapshot.last_rejected_step =
                current_last_rejected_sum_counts;
            foc_current_trip_snapshot.median_u[0] = current_med_u[0];
            foc_current_trip_snapshot.median_u[1] = current_med_u[1];
            foc_current_trip_snapshot.median_u[2] = current_med_u[2];
            foc_current_trip_snapshot.median_v[0] = current_med_v[0];
            foc_current_trip_snapshot.median_v[1] = current_med_v[1];
            foc_current_trip_snapshot.median_v[2] = current_med_v[2];
            foc_current_trip_snapshot.vbus_raw = analog_live_pc4_raw;
            foc_current_trip_snapshot.vbus_age_ms = vbus_age_ms;
            foc_current_trip_snapshot.analog_sample_count = analog_live_sample_count;
            foc_current_trip_snapshot.analog_error_count = analog_live_error_count;
            foc_current_trip_snapshot.vbus_valid =
                ((analog_live_valid != 0U) &&
                 (vbus_age_ms <= ANALOG_LIVE_FRESH_MS)) ? 1U : 0U;
#if defined(FOC_CURRENT_TREND4)
#include "foc_overcurrent_shadow_capture.inc"
#endif
            __DMB();
            foc_current_trip_snapshot.valid = 1U;
        }
        return;
    }

#if defined(FOC_CURRENT_TREND4)
    FocOcShadow_Push(&foc_oc_shadow, injected_seq_count,
        FocOcShadow_Mask(physical_u_A,physical_v_A,physical_w_A,FOC_CURRENT_TRIP_A),
        u_physical<=ADC_FULL_SCALE && v_physical<=ADC_FULL_SCALE);
#if defined(FOC_FILTERED_OBSERVE_ONLY)
    /* Available-output sequence, delayed one physical pair. No result here
     * authorizes PWM, and this observer never participates in a stop gate. */
    FocOcShadow_Push(&foc_filtered_oc_shadow, injected_seq_count,
        FocOcShadow_Mask(filtered_u_A,filtered_v_A,filtered_w_A,FOC_CURRENT_TRIP_A),1U);
#endif
#endif
#endif /* FOC_FEEDBACK_SAFETY_BINDING: legacy policy remains unchanged otherwise */
    FocProfile_Mark(FOC_PROF_OTHER);
    i_alpha = iu_A;
    i_beta = (iu_A + 2.0f * iv_A) * 0.57735026919f;

    theta = encoder_theta_e_pred;
#if defined(FOC_CURRENT_TREND4)
#if defined(FOC_PROTECTED_CLOSED_LOOP)
    theta=cl_frame.measurement_angle;
#elif defined(FOC_FEEDBACK_SAFETY_BINDING)
    theta = foc_feedback_control_frame.measurement_angle;
#else
    /* Park uses the angle estimate stored with the delayed center sample. */
    theta = current_trend4_angle.center;
#endif
#endif
#if defined(FOC_FAST_MATH)
    if (!FocFast_SinCos(theta,&s,&c)) {
        ProtectedLoop_EmergencyOff(CL_BAD_ENCODER); return;
    }
#else
    s = sinf(theta);
    c = cosf(theta);
#endif

    id_A =  i_alpha * c + i_beta * s;
    iq_A = -i_alpha * s + i_beta * c;
    FocProfile_Mark(FOC_PROF_TRANSFORM);

#if defined(FOC_MOTOR_IDENTIFICATION_DIAG)
    /* Diagnostic-only reference owner; PI and all math below are unchanged. */
    if (!MotorIdent_Ref(id_A,iq_A)) return;
#endif
#if defined(FOC_IDENT_VOLTAGE_STEP_DIAG)
    /* Exclusive manual voltage diagnostic: no PI/error/integrator update.
     * IDLE/READY/non-active always generates neutral, never stale PI output. */
    MotorIdent_Voltage(&motor_ident,cl_frame.source_us,&vd,&vq);
#else
#if defined(FOC_CURRENT_STEP_AB_DIAG)
    if (!CurrentStep_FocReference()) return;
#endif
    err_d = foc_id_ref_A - id_A;
    err_q = foc_iq_ref_A - iq_A;

    /*
     * PI controller:
     *   Kp ~= L*w_c = 0.08 V/A
     *   Ki ~= R*w_c = 188 V/(A*s)
     * for roughly 300 Hz initial current-loop bandwidth using the historical
     * R ~= 0.10 ohm and L ~= 42.3 uH motor estimates. Opt-in A comparison
     * selects axis-specific gains in current_pi_identified_candidate.h;
     * PI order, vector saturation and integrator tracking are unchanged.
     */
#if FOC_CURRENT_FAULT_TRACE_ENABLE
    FocCurrentTrace_Pi(); /* Diagnostic only: actual PI-update reachability. */
#endif
    foc_int_d_V += FOC_CURRENT_KI_D_V_PER_AS * err_d * FOC_TS_S;
    foc_int_q_V += FOC_CURRENT_KI_Q_V_PER_AS * err_q * FOC_TS_S;

    foc_int_d_V = ClampFloat(foc_int_d_V,
                             -FOC_INTEGRATOR_LIMIT_V,
                              FOC_INTEGRATOR_LIMIT_V);
    foc_int_q_V = ClampFloat(foc_int_q_V,
                             -FOC_INTEGRATOR_LIMIT_V,
                              FOC_INTEGRATOR_LIMIT_V);

    vd = FOC_CURRENT_KP_D_V_PER_A * err_d + foc_int_d_V;
    vq = FOC_CURRENT_KP_Q_V_PER_A * err_q + foc_int_q_V;

#if defined(FOC_DQ_DECOUPLING_CANDIDATE)
    float vd_ff,vq_ff;
    uint8_t dq_on=dq_decoupling_enabled;
    float dq_omega=encoder_omega_e_rad_s;
    if (!FocDqDecoupling_Apply(dq_on,dq_omega,id_A,iq_A,&vd_ff,&vq_ff)) {
        dq_decoupling_frame.valid=0U;
        ProtectedLoop_EmergencyOff(CL_BAD_OUTPUT); return;
    }
    float vd_pi=vd,vq_pi=vq;
    /* OFF bypasses even +0, preserving the historical PI bit pattern. */
    if (dq_on) { vd+=vd_ff; vq+=vq_ff; }
#endif

#if defined(FOC_BEMF_CANDIDATE)
    float bemf_q,bemf_vd_pi=vd,bemf_vq_pi=vq;
    uint8_t bemf_on=bemf_enabled;
    float bemf_omega=encoder_omega_e_rad_s;
#if defined(FOC_BEMF_GAIN_DIAG)
    if (!FocBemfGain_Apply(bemf_on,bemf_omega,bemf_gain_percent,&bemf_q)) {
#else
    if (!FocBemf_Apply(bemf_on,bemf_omega,&bemf_q)) {
#endif
        bemf_frame.valid=0U;
        ProtectedLoop_EmergencyOff(CL_BAD_OUTPUT); return;
    }
    /* OFF skips even +0. No output/pipeline owner is changed here. */
    if (bemf_on) {
        vq+=bemf_q;
        if (!isfinite(vq)) {
            bemf_frame.valid=0U;
            ProtectedLoop_EmergencyOff(CL_BAD_OUTPUT); return;
        }
    }
#endif

    /*
     * Vector-voltage limit. 0.8 V is intentionally small for the first
     * closed-loop test so the motor cannot run away to a high no-load speed.
     */
    mag2 = vd * vd + vq * vq;
    limit2 = FOC_VOLTAGE_LIMIT_V * FOC_VOLTAGE_LIMIT_V;
#if defined(FOC_CURRENT_STEP_AB_DIAG)
    current_step_out_d=vd;current_step_out_q=vq;
    current_step_saturated=(uint8_t)(mag2>limit2);
#endif

    if (mag2 > limit2)
    {
        float scale = FOC_VOLTAGE_LIMIT_V / sqrtf(mag2);

        vd *= scale;
        vq *= scale;

        /*
         * Simple tracking anti-windup: after vector saturation, move each
         * integrator to the value consistent with the saturated command.
         */
        foc_int_d_V = vd - FOC_CURRENT_KP_D_V_PER_A * err_d;
        foc_int_q_V = vq - FOC_CURRENT_KP_Q_V_PER_A * err_q;
#if defined(FOC_BEMF_CANDIDATE)
        /* Saturation tracking owns PI voltage only, not PI+back-EMF. */
        if (bemf_on) foc_int_q_V-=bemf_q;
#endif
#if defined(FOC_DQ_DECOUPLING_CANDIDATE)
        /* Track the PI contribution, NOT total PI+feedforward voltage. */
        if (dq_on) { foc_int_d_V-=vd_ff; foc_int_q_V-=vq_ff; }
#endif

        foc_int_d_V = ClampFloat(foc_int_d_V,
                                 -FOC_INTEGRATOR_LIMIT_V,
                                  FOC_INTEGRATOR_LIMIT_V);
        foc_int_q_V = ClampFloat(foc_int_q_V,
                                 -FOC_INTEGRATOR_LIMIT_V,
                                  FOC_INTEGRATOR_LIMIT_V);
    }

#if defined(FOC_DQ_DECOUPLING_CANDIDATE)
    /* Single ISR writer; task reader masks interrupts for a bounded copy.
     * Fixed binary latest-frame assignment only, not a historical trace. */
    dq_decoupling_frame=(FocDqDecouplingFrame){
        .seq=injected_seq_count,.source_us=cl_frame.source_us,.enabled=dq_on,
        .saturated=(uint32_t)(mag2>limit2),.valid=1U,
        .omega_e=dq_omega,.id=id_A,.iq=iq_A,.vd_pi=vd_pi,.vq_pi=vq_pi,
        .vd_ff=vd_ff,.vq_ff=vq_ff,.vd=vd,.vq=vq};
#if defined(FOC_DQ_AUDIT_ENABLE)
    _Static_assert(POLE_PAIRS==10U,"DQA1 independent speed conversion assumes existing 10 pole pairs");
    uint32_t dq_flags=(dq_on ? DQA_ON : 0U) | (cl_session.state==CL_RUNNING ? DQA_RUNNING : 0U) |
        (mag2>limit2 ? DQA_SATURATED : 0U) | ((uint32_t)DECOUPLING_SIGN_MODE<<8);
    if (motor_control_mode==MOTOR_MODE_SPEED && fabsf(speed_ref_rpm-speed_target_rpm)<=.001f &&
        fabsf(speed_scurve.acceleration_rpm_s)<=.001f) dq_flags|=DQA_CRUISE;
    FocDqAuditFrame dq_record={.seq=injected_seq_count,.us=cl_frame.source_us,.flags=dq_flags,
        .mech_rpm=encoder_speed_rpm,.we_rad_s=dq_omega,.id=id_A,.iq=iq_A,
        .vd_pi=vd_pi,.vq_pi=vq_pi,.vd_dec=vd_ff,.vq_dec=vq_ff,.vd_cmd=vd,.vq_cmd=vq,
        .speed_ref=speed_ref_rpm,.speed_meas=encoder_speed_rpm};
    FocDqAudit_Record(&dq_audit,&dq_record);
#endif
#endif
#if defined(FOC_BEMF_CANDIDATE)
    bemf_frame=(FocBemfFrame){.seq=injected_seq_count,.source_us=cl_frame.source_us,
        .enabled=bemf_on,.saturated=(uint32_t)(mag2>limit2),.valid=1U,
        .omega_e=bemf_omega,.id=id_A,.iq=iq_A,.vd_pi=bemf_vd_pi,.vq_pi=bemf_vq_pi,
        .vq_ff=bemf_q,.vd=vd,.vq=vq};
#endif
#endif /* Exclusive voltage diagnostic, original current PI otherwise. */
    FocProfile_Mark(FOC_PROF_PI);
    /* Inverse Park. */
#if defined(FOC_CURRENT_TREND4) && !defined(FOC_FAST_CURRENT_REJECT)
    /* Historical delayed feedback needs a second angle. Fast reject uses
     * this physical pair and the SAME angle, so reuse its checked sin/cos. */
#if defined(FOC_PROTECTED_CLOSED_LOOP)
#if defined(FOC_FAST_MATH)
    if (!FocFast_SinCos(cl_frame.actuation_angle,&s,&c)) {
        ProtectedLoop_EmergencyOff(CL_BAD_ENCODER); return;
    }
#else
    s=sinf(cl_frame.actuation_angle); c=cosf(cl_frame.actuation_angle);
#endif
#elif defined(FOC_FEEDBACK_SAFETY_BINDING)
    s = sinf(foc_feedback_control_frame.actuation_angle);
    c = cosf(foc_feedback_control_frame.actuation_angle);
#else
    s = sinf(encoder_theta_e_pred);
    c = cosf(encoder_theta_e_pred);
#endif
#endif
    v_alpha = vd * c - vq * s;
    v_beta  = vd * s + vq * c;
    FocProfile_Mark(FOC_PROF_INVERSE);

    /*
     * alpha-beta -> three phase, then centered zero-sequence injection.
     * This is the usual min/max common-mode form of SVPWM.
     */
    vu = v_alpha;
    vv = -0.5f * v_alpha + 0.86602540378f * v_beta;
    vw = -0.5f * v_alpha - 0.86602540378f * v_beta;

    vmax = vu;
    if (vv > vmax) vmax = vv;
    if (vw > vmax) vmax = vw;

    vmin = vu;
    if (vv < vmin) vmin = vv;
    if (vw < vmin) vmin = vw;

    voffset = -0.5f * (vmax + vmin);

    vu += voffset;
    vv += voffset;
    vw += voffset;

    du = 0.5f + vu / FOC_DC_BUS_V;
    dv = 0.5f + vv / FOC_DC_BUS_V;
    dw = 0.5f + vw / FOC_DC_BUS_V;

    FocProfile_Mark(FOC_PROF_SVPWM);
    PWM_SetDuty(du, dv, dw);
    FocProfile_Mark(FOC_PROF_DUTY);

    foc_id_A = id_A;
    foc_iq_A = iq_A;
#if defined(FOC_MECHANICAL_IDENT_DIAG)
    /* Publication only; original PI, PWM and protection owners stay unchanged. */
    uint32_t mechanical_begin=DWT->CYCCNT;
    Mechanical_Publish(&mechanical_current,cl_frame.source_seq,cl_frame.source_us,
        AS5047P_DmaNowUs(),id_A,iq_A,mag2>limit2?MEC_SATURATED:0U);
    uint32_t mechanical_cycles=DWT->CYCCNT-mechanical_begin;
    if (mechanical_cycles>mechanical_capture.publish_cycles_max)
        mechanical_capture.publish_cycles_max=mechanical_cycles;
#endif
#if defined(FOC_KA_SYNC_DIAG) || defined(FOC_KA_FULL_DIAG)
    /* Diagnostic only. Source_us is the existing pair-read timestamp,
     * not a claim to measure the physical ADC sampling aperture. */
    uint32_t sync_begin=DWT->CYCCNT;
    KaSync_Publish(&ka_sync_current,cl_frame.source_seq,cl_frame.source_us,AS5047P_DmaNowUs(),iq_A);
    uint32_t sync_cycles=DWT->CYCCNT-sync_begin;
#if defined(FOC_KA_FULL_DIAG)
    if (sync_cycles>ka_full_diagnostic.publish_cycles_max) ka_full_diagnostic.publish_cycles_max=sync_cycles;
#else
    if (sync_cycles>ka_sync_diagnostic.publish_cycles_max) ka_sync_diagnostic.publish_cycles_max=sync_cycles;
#endif
#endif
    foc_vd_V = vd;
    foc_vq_V = vq;
#if defined(FOC_CURRENT_STEP_AB_DIAG)
    CurrentStep_Capture();
#endif

#if defined(FOC_MOTOR_IDENTIFICATION_DIAG)
    /* Binary record only; no UART/estimation/heap in the fast path. */
    MotorIdent_Capture();
#endif
    foc_duty_u = du;
    foc_duty_v = dv;
    foc_duty_w = dw;

    /* Predict electrical angle at the 20 kHz current-loop rate. */
#if defined(FOC_FAST_CURRENT_REJECT)
    ProtectedLoop_AdvanceAngle();
#else
    encoder_theta_e_pred += encoder_omega_e_rad_s * FOC_TS_S;
    while (encoder_theta_e_pred >= TWO_PI_F) encoder_theta_e_pred -= TWO_PI_F;
    while (encoder_theta_e_pred < 0.0f) encoder_theta_e_pred += TWO_PI_F;
#endif

    foc_control_count++;
}


/*
 * Update AS5047P, estimate mechanical speed, correct predicted electrical
 * angle, then run the outer 1 kHz-ish speed PI. dt_s is the ACTUAL elapsed
 * time; this is important because UART status output is blocking.
 */
