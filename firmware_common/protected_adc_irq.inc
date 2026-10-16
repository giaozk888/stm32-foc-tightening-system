/* Protected profile only: one rank on each independent ADC, same TIM1 edge.
 * Never enter HAL's injected-completion path: it clears JEOS AFTER calling
 * the application, which can erase a new completion during lengthy FOC math.
 * Error/watchdog sources still go through HAL, only after power is locked off.
 * Included after FOC_CurrentLoopStep and the protected binding declarations. */
FOC_HOT_PATH
void ProtectedLoop_AdcIrq(void)
{
    uint32_t protected_begin=AS5047P_DmaNowUs();
    uint32_t mask=__get_PRIMASK(); __disable_irq();
#if defined(FOC_FAST_MATH)
    uint32_t work_cycles=DWT->CYCCNT;
    uint32_t irq_body_start=FocIrqLoad_Read();
#endif
    const uint32_t completion=ADC_IT_JEOC | ADC_IT_JEOS;
    uint32_t status1=hadc1.Instance->ISR, status2=hadc2.Instance->ISR;
    uint32_t pending1=status1 & hadc1.Instance->IER;
    uint32_t pending2=status2 & hadc2.Instance->IER;
    /* ADC2 must not become a second completion owner. Any enabled other
     * source (AWD/OVR/JQOVF etc.) is fail-closed, not silently suppressed. */
    if ((pending1 & ~completion) || pending2 ||
        (hadc1.Instance->IER & ADC_IT_JEOC) ||
        (hadc2.Instance->IER & completion) ||
        ((pending1 & completion) && !FocAdcTiming_PairReady())) {
        ProtectedLoop_EmergencyOff(CL_BAD_ADC);
        adc_fault=1U;
        __HAL_ADC_DISABLE_IT(&hadc1, completion);
        __HAL_ADC_DISABLE_IT(&hadc2, completion);
        __set_PRIMASK(mask);
        /* No injected callback/tail-clear is possible now, even if a new
         * conversion completes during HAL's error reporting. Never re-arm. */
        if (pending1 & ~completion) HAL_ADC_IRQHandler(&hadc1);
        if (pending2 & ~completion) HAL_ADC_IRQHandler(&hadc2);
        return;
    }
    if (!(pending1 & ADC_IT_JEOS)) { __set_PRIMASK(mask); return; }
    uint16_t u=(uint16_t)hadc1.Instance->JDR1;
    uint16_t v=(uint16_t)hadc2.Instance->JDR1;
    /* Read -> acknowledge both -> release mask -> filter/compute. No W1C
     * completion write is allowed after computation in this IRQ path. */
    __HAL_ADC_CLEAR_FLAG(&hadc1, ADC_FLAG_JEOC | ADC_FLAG_JEOS);
    __HAL_ADC_CLEAR_FLAG(&hadc2, ADC_FLAG_JEOC | ADC_FLAG_JEOS);
    SET_BIT(hadc1.State, HAL_ADC_STATE_INJ_EOC);
#if defined(FOC_IRQ_SOURCE_TRACE)
    FocIrqSource_FrameBegin();
#endif
    __DMB(); __set_PRIMASK(mask);
    FocAdcTiming_RecordRaw(u,v);
    ++injected_seq_count;
    if (ProtectedLoop_Pair(u,v)) {
#if defined(FOC_RC_DEFERRED_SHADOW)
        ProtectedLoop_DeferredProbe();
#endif
#if defined(FOC_FAST_MATH)
        uint32_t math_begin=AS5047P_DmaNowUs();
        uint32_t pair_us=math_begin-protected_begin;
        if (pair_us>cl_pair_max_us) cl_pair_max_us=pair_us;
#endif
        iu_inj_raw=cl_frame.u; iv_inj_raw=cl_frame.v; ++current_valid_count;
#if defined(FOC_LATEST_ORIGINAL_FSM)
        if (cl_session.state!=CL_RUNNING) FocCurrentPi_Reset(&foc_int_d_V,&foc_int_q_V);
#endif
        FOC_CurrentLoopStep(iu_inj_raw,iv_inj_raw,u,v);
#if defined(FOC_LATEST_ORIGINAL_FSM)
        /* READY computes real feedback but cannot charge PI for a later START. */
        if (cl_session.state!=CL_RUNNING) FocCurrentPi_Reset(&foc_int_d_V,&foc_int_q_V);
#endif
#if defined(FOC_FAST_MATH)
        uint32_t math_us=AS5047P_DmaNowUs()-math_begin;
        if (math_us>cl_math_max_us) cl_math_max_us=math_us;
        /* Take both counters in a short mask: the two snapshots must share
         * the same boundary even if the measured IRQ arrives right here.
         * CPU includes entry/exit overhead and all uninstrumented work. */
        mask=__get_PRIMASK(); __disable_irq();
#if defined(FOC_IRQ_SOURCE_TRACE)
        FocIrqSource_FrameEnd(&cl_frame_irq);
#endif
        uint32_t irq_cycles=FocIrqLoad_Read()-irq_body_start;
        uint32_t wall_cycles=DWT->CYCCNT-work_cycles;
        if (irq_cycles>cl_preempt_max_cyc) cl_preempt_max_cyc=irq_cycles;
        if (wall_cycles>=irq_cycles && wall_cycles-irq_cycles>cl_cpu_max_cyc)
            cl_cpu_max_cyc=wall_cycles-irq_cycles;
#if defined(FOC_PAIR_FAST_PATH)
        cl_frame_cost=(FocFrameCost){.seq=cl_seq,.pair_us=pair_us,.math_us=math_us,
            .wall_cyc=wall_cycles,.irq_cyc=irq_cycles};
#endif
        __set_PRIMASK(mask);
#endif
        ProtectedLoop_WorkEnd(protected_begin);
    }
#if defined(FOC_IRQ_SOURCE_TRACE)
    else FocIrqSource_FrameEnd(0); /* Calibration/fault path is not a FOC frame. */
#endif
}
