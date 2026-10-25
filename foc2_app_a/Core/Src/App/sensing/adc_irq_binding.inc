/* App A sensing/adc_irq_binding.inc: private binding, included once by main.c.
 * Keep the declared include order and original control/IRQ ownership. */
#if defined(FOC_PROTECTED_CLOSED_LOOP)
#include "protected_adc_irq.inc"
#endif
void HAL_ADCEx_InjectedConvCpltCallback(ADC_HandleTypeDef *hadc)
{
#if defined(FOC_PROTECTED_CLOSED_LOOP)
    /* This profile has a separate early-ack entry. Unexpected HAL dispatch
     * must fail closed, not create a second filtering/completion owner. */
    (void)hadc;
    ProtectedLoop_EmergencyOff(CL_BAD_ADC);
    adc_fault=1U;
    __HAL_ADC_DISABLE_IT(&hadc1, ADC_IT_JEOS | ADC_IT_JEOC);
    __HAL_ADC_DISABLE_IT(&hadc2, ADC_IT_JEOS | ADC_IT_JEOC);
    return;
#endif
#if defined(ZERO_RETEST_BOOT)
    if (hadc->Instance == ADC1) ZeroRetest_InjectedPair();
    return; /* Never reach current filters, encoder, or FOC in this profile. */
#endif
    /*
     * ADC1 owns the interrupt callback. ADC1 and ADC2 are independent ADCs,
     * but both are armed by the same TIM1 TRGO2 edge with identical sampling
     * time, so ADC2 JDR1 belongs to the same PWM sampling event.
     */
    if (hadc->Instance == ADC1)
    {
#if defined(FOC_ADC_WINDOW)
        if (!FocAdcTiming_PairReady())
        {
#if defined(FOC_PROTECTED_CLOSED_LOOP)
            ProtectedLoop_EmergencyOff(CL_BAD_ADC);
#endif
#if defined(FOC_FEEDBACK_SAFETY_BINDING)
            FocFeedbackBinding_EmergencyOff(FOC_FP_ADC_INVALID);
#endif
            adc_fault = 1U;
            foc_enable = 0U;
            foc_fault = 1U;
            foc_fault_reason = FOC_FAULT_ADC_WINDOW;
            DRIVER_SD_GPIO_Port->BSRR = (uint32_t)DRIVER_SD_Pin << 16U;
            TIM1->BDTR &= ~TIM_BDTR_MOE;
            FaultDiag_Motor(FOC_FAULT_ADC_WINDOW);
            __HAL_ADC_CLEAR_FLAG(&hadc2, ADC_FLAG_JEOC | ADC_FLAG_JEOS);
            /* A late ADC2 completion must not masquerade as next cycle's
             * result. Latch off the completion chain until a fresh boot. */
            __HAL_ADC_DISABLE_IT(&hadc1, ADC_IT_JEOS | ADC_IT_JEOC);
            __DSB();
            return;
        }
#endif
        uint16_t u = (uint16_t)HAL_ADCEx_InjectedGetValue(
            &hadc1, ADC_INJECTED_RANK_1);

        uint16_t v = (uint16_t)HAL_ADCEx_InjectedGetValue(
            &hadc2, ADC_INJECTED_RANK_1);

        /*
         * ADC2 is intentionally used without an ADC2 interrupt. Reading JDR1
         * consumes its JEOC result; clear JEOS as housekeeping after the read.
         */
        __HAL_ADC_CLEAR_FLAG(&hadc2, ADC_FLAG_JEOC | ADC_FLAG_JEOS);
#if defined(FOC_ADC_WINDOW)
        FocAdcTiming_RecordRaw(u, v); /* before median/step filtering */
#endif

        injected_seq_count++;
#if defined(FOC_ISOLATED_CONCURRENCY)
#if defined(FOC_FEEDBACK_SAFETY_BINDING)
        if (!FocFeedbackBinding_PhysicalSeen(u, v)) return;
#endif
        if (IsolatedZero_Feed(u, v)) return;
#endif
#if defined(FOC_FEEDBACK_SAFETY_BINDING)
        /* Single filtering/protection owner; never also run the legacy filter. */
        uint32_t feedback_start_us = foc_feedback_last_us;
        if (FocFeedbackBinding_Control(u, v)) {
            iu_inj_raw = foc_feedback_control_frame.u;
            iv_inj_raw = foc_feedback_control_frame.v;
            current_valid_count++;
            FOC_CurrentLoopStep(iu_inj_raw, iv_inj_raw, u, v);
        }
        FocFeedbackBinding_WorkEnd(feedback_start_us);
        return;
#endif

        /*
         * PWM-on zero calibration uses only the two physically measured
         * simultaneous currents.
         */
        if (run_zero_cal_active != 0U)
        {
            uint16_t filtered_u = 0U, filtered_v = 0U;
            int admission = FocRunZeroMedian_Push(&run_zero_median, u, v,
                iu_zero_raw, iv_zero_raw, RUN_ZERO_MAX_DELTA_COUNTS,
                &filtered_u, &filtered_v);
            if (admission > 0)
            {
                run_zero_sum_u += filtered_u;
                run_zero_sum_v += filtered_v;
                run_zero_valid_count++;

                if (run_zero_valid_count >= RUN_ZERO_CAL_SAMPLES)
                {
                    run_zero_cal_active = 0U;
                    run_zero_cal_done = 1U;
                }
            }
            else if (admission < 0)
            {
                run_zero_reject_count++;
            }
        }

        /*
         * Reconstruct W in ADC-count units:
         *   dW = -(dU + dV)
         *
         * iw_zero_raw is retained only as the center of this pseudo-raw
         * representation so the existing mA conversion/printing path remains
         * unchanged.
         */
        {
            int32_t du = (int32_t)u - (int32_t)iu_zero_raw;
            int32_t dv = (int32_t)v - (int32_t)iv_zero_raw;
            int32_t w_recon = (int32_t)iw_zero_raw - du - dv;

            if (w_recon < 0)
                w_recon = 0;
            else if (w_recon > (int32_t)ADC_FULL_SCALE)
                w_recon = (int32_t)ADC_FULL_SCALE;

            if (current_filter_enable != 0U)
            {
                int32_t step_u = 0;
                int32_t step_v = 0;
                uint8_t frame_ok = 1U;

                if (current_prev_raw_valid != 0U)
                {
                    step_u = (int32_t)u - (int32_t)current_prev_raw_u;
                    step_v = (int32_t)v - (int32_t)current_prev_raw_v;

                    if ((step_u < -CURRENT_STEP_REJECT_COUNTS) ||
                        (step_u >  CURRENT_STEP_REJECT_COUNTS) ||
                        (step_v < -CURRENT_STEP_REJECT_COUNTS) ||
                        (step_v >  CURRENT_STEP_REJECT_COUNTS))
                    {
                        frame_ok = 0U;
                    }
                }

                /*
                 * ALWAYS advance the physical previous-sample reference.
                 * This prevents one rejected spike from causing a permanent
                 * reject streak against a stale last-accepted sample.
                 */
                current_prev_raw_u = u;
                current_prev_raw_v = v;
                current_prev_raw_valid = 1U;

#if defined(FOC_CURRENT_SPIKE_ONLY)
#if defined(FOC_CURRENT_TREND4)
                FocTrend4Angle_Push(&current_trend4_angle, encoder_theta_e_pred);
#endif
#include "foc_current_spike_runtime.inc"
#if defined(FOC_CURRENT_TREND4)
                if (spike_ready && spike_u<=ADC_FULL_SCALE &&
                    spike_v<=ADC_FULL_SCALE && adc_fault==0U) {
                    foc_trend_pairs=FocOcShadow_Inc(foc_trend_pairs);
                    if (current_spike_filter.last_spike_mask) foc_trend_changed=FocOcShadow_Inc(foc_trend_changed);
                    if (current_spike_filter.last_spike_mask & 1U) foc_trend_u_changed=FocOcShadow_Inc(foc_trend_u_changed);
                    if (current_spike_filter.last_spike_mask & 2U) foc_trend_v_changed=FocOcShadow_Inc(foc_trend_v_changed);
                }
#endif
#else
                if (frame_ok != 0U)
                {
                    uint16_t u_pub = u;
                    uint16_t v_pub = v;
                    int32_t du_pub;
                    int32_t dv_pub;
                    int32_t w_pub;

                    /*
                     * Only samples that already passed the physical step gate
                     * enter the median buffer.
                     */
                    current_med_u[current_med_index] = u;
                    current_med_v[current_med_index] = v;
                    current_med_index =
                        (uint8_t)((current_med_index + 1U) % 3U);

                    if (current_med_count < 3U)
                        current_med_count++;

                    if (current_med_count >= 3U)
                    {
                        u_pub = Median3_U16(current_med_u[0],
                                            current_med_u[1],
                                            current_med_u[2]);
                        v_pub = Median3_U16(current_med_v[0],
                                            current_med_v[1],
                                            current_med_v[2]);
                    }

                    /*
                     * Reconstruct W from the exact U/V pair that is published
                     * to the FOC, so Clarke/Park always sees a self-consistent
                     * three-phase current set.
                     */
                    du_pub =
                        (int32_t)u_pub - (int32_t)iu_zero_raw;
                    dv_pub =
                        (int32_t)v_pub - (int32_t)iv_zero_raw;
                    w_pub =
                        (int32_t)iw_zero_raw - du_pub - dv_pub;

                    if (w_pub < 0)
                        w_pub = 0;
                    else if (w_pub > (int32_t)ADC_FULL_SCALE)
                        w_pub = (int32_t)ADC_FULL_SCALE;

                    iu_inj_raw = u_pub;
                    iv_inj_raw = v_pub;
                    iw_inj_raw = (uint16_t)w_pub;

                    current_valid_count++;
                    current_reject_streak = 0U;
                }
                else
                {
                    int32_t abs_u = (step_u >= 0) ? step_u : -step_u;
                    int32_t abs_v = (step_v >= 0) ? step_v : -step_v;

                    current_reject_count++;
                    current_reject_streak++;
                    current_last_rejected_sum_counts =
                        (abs_u > abs_v) ? abs_u : abs_v;

                    /*
                     * A true isolated spike normally rejects at most the spike
                     * sample and possibly the return sample. 20 consecutive
                     * raw-to-raw large jumps still indicates a real problem.
                     */
                    if (current_reject_streak >= CURRENT_REJECT_STREAK_LIMIT)
                    {
                        adc_fault = 1U;

                        HAL_GPIO_WritePin(DRIVER_SD_GPIO_Port,
                                          DRIVER_SD_Pin,
                                          GPIO_PIN_RESET);
                    }
                }
#endif
            }
            else
            {
                iu_inj_raw = u;
                iv_inj_raw = v;
                iw_inj_raw = (uint16_t)w_recon;
            }

            /*
             * Run the current PI on the latest ACCEPTED current frame.
             * If the physical sample was rejected as a spike, iu_inj_raw /
             * iv_inj_raw still contain the previous valid frame, so the
             * controller automatically holds that current sample briefly.
             */
#if defined(FOC_ISOLATED_CONCURRENCY)
            if (IsolatedBench_Active() && (run_zero_cal_active == 0U))
#else
            if ((foc_enable != 0U) && (run_zero_cal_active == 0U))
#endif
            {
#if defined(FOC_CURRENT_TREND4)
                /* No PI update on the three startup history pairs. */
                if (current_spike_filter.count < FOC_CURRENT_HISTORY_PAIRS ||
                    adc_fault != 0U) return;
#endif
                FOC_CurrentLoopStep(iu_inj_raw, iv_inj_raw, u, v);
            }
        }
    }
}


void HAL_ADC_ErrorCallback(ADC_HandleTypeDef *hadc)
{
#if defined(FOC_PROTECTED_CLOSED_LOOP)
    ProtectedLoop_EmergencyOff(CL_BAD_ADC);
#endif
#if defined(FOC_FEEDBACK_SAFETY_BINDING)
    FocFeedbackBinding_EmergencyOff(FOC_FP_ADC_INVALID);
#endif
#if defined(SWITCH_FEEDBACK_DIAGNOSTIC)
    SwitchFeedback_EmergencyOff(8U);
#endif
#if defined(ADC_DMA_RAW_DIAGNOSTIC)
    AdcDmaDiag_Error(hadc);
#endif
    if ((hadc->Instance == ADC1) || (hadc->Instance == ADC2))
    {
        adc_fault = 1U;
        HAL_GPIO_WritePin(DRIVER_SD_GPIO_Port,
                          DRIVER_SD_Pin,
                          GPIO_PIN_RESET);
        FaultDiag_Motor(FOC_FAULT_ADC_CHAIN_STALE);
    }
}
