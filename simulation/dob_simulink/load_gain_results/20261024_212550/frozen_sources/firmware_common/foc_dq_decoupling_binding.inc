/* Task-context console only. No UART/printf or log formatting in ADC ISR. */
static int32_t DqWire_Scaled(float value,float scale)
{
    /* nano printf has no %f. Truncate toward zero in explicit wire units;
     * INT32_MIN denotes an unrepresentable diagnostic, never a control gate. */
    float scaled=value*scale;
    if (!isfinite(scaled) || scaled < -2147483648.0f || scaled >= 2147483648.0f)
        return INT32_MIN;
    return (int32_t)scaled;
}
static uint8_t DqDecoupling_Command(const char *cmd,char *out,size_t size)
{
    if (strncmp(cmd,"MOTOR TEST DQ ",14U)) return 0U;
    const char *arg=cmd+14U;
#if defined(FOC_DQ_AUDIT_ENABLE)
    if (!strcmp(arg,"AUDIT STATUS")) {
        snprintf(out,size,"OK DQA VERSION=1 SIGN_TEST=%u MODE=%u LD_NH=%ld LQ_NH=%ld LOG_US=%u START_US=%u STATIONARY_MRPM=1000",
            (unsigned)DECOUPLING_SIGN_TEST,(unsigned)DECOUPLING_SIGN_MODE,
            (long)(FOC_DQ_LD_H*1e9f+.5f),(long)(FOC_DQ_LQ_H*1e9f+.5f),
            (unsigned)DQ_AUDIT_LOG_US,(unsigned)DQ_AUDIT_STARTUP_US);
        return 1U;
    }
#endif
    uint8_t toggle=(uint8_t)(!strcmp(arg,"ON") || !strcmp(arg,"OFF"));
    if (!toggle && strcmp(arg,"STATUS") && strcmp(arg,"VOLTAGE")) {
        snprintf(out,size,"ERR DQ COMMAND"); return 1U;
    }
    uint32_t mask=__get_PRIMASK(); __disable_irq();
    if (toggle) {
        if (cl_session.state==CL_RUNNING || Tightening_IsBusy() ||
            tightening_start_request || tightening_stop_request ||
            motor_control_mode!=MOTOR_MODE_IDLE ||
            (DRIVER_SD_GPIO_Port->ODR & DRIVER_SD_Pin) ||
            (TIM1->BDTR & (TIM_BDTR_MOE|TIM_BDTR_AOE)) || TIM1->CCER) {
            __set_PRIMASK(mask);
            snprintf(out,size,"ERR DQ BUSY_OR_OUTPUT_ENABLED"); return 1U;
        }
        dq_decoupling_enabled=(uint8_t)(!strcmp(arg,"ON"));
        dq_decoupling_frame.valid=0U;
    }
    FocDqDecouplingFrame f=dq_decoupling_frame;
    uint8_t enabled=dq_decoupling_enabled;
    __set_PRIMASK(mask);
    if (!strcmp(arg,"VOLTAGE")) {
        snprintf(out,size,"OK DQ VALID=%lu SEQ=%lu US=%lu SAT=%lu VD_PI_UV=%ld VQ_PI_UV=%ld VD_FF_UV=%ld VQ_FF_UV=%ld VD_UV=%ld VQ_UV=%ld",
            (unsigned long)f.valid,(unsigned long)f.seq,(unsigned long)f.source_us,
            (unsigned long)f.saturated,(long)DqWire_Scaled(f.vd_pi,1e6f),(long)DqWire_Scaled(f.vq_pi,1e6f),
            (long)DqWire_Scaled(f.vd_ff,1e6f),(long)DqWire_Scaled(f.vq_ff,1e6f),
            (long)DqWire_Scaled(f.vd,1e6f),(long)DqWire_Scaled(f.vq,1e6f));
    } else {
        snprintf(out,size,"OK DQ ON=%u VALID=%lu SEQ=%lu FRAME_ON=%lu OMEGA_E_MRAD_S=%ld ID_UA=%ld IQ_UA=%ld LD_NH=%ld LQ_NH=%ld",
            enabled,(unsigned long)f.valid,(unsigned long)f.seq,(unsigned long)f.enabled,
            (long)DqWire_Scaled(f.omega_e,1e3f),(long)DqWire_Scaled(f.id,1e6f),
            (long)DqWire_Scaled(f.iq,1e6f),
            (long)(FOC_DQ_LD_H*1e9f+.5f),(long)(FOC_DQ_LQ_H*1e9f+.5f));
    }
    return 1U;
}
#if defined(FOC_DQ_AUDIT_ENABLE)
static void DqAudit_Monitor(void)
{
    static uint32_t last_seq,last_log_us,last_stats_us;
    /* Coherent task snapshot only; no format/log inside the short mask. */
    uint32_t mask=__get_PRIMASK();__disable_irq();
    FocDqAuditFrame f=dq_audit.latest;
    FocDqAuditStats s=dq_audit.stats;
    __set_PRIMASK(mask);
    if (f.seq && f.seq!=last_seq && (uint32_t)(f.us-last_log_us)>=DQ_AUDIT_LOG_US) {
        last_seq=f.seq;last_log_us=f.us;FocDqAudit_LogFrame(&f);
    }
    if (f.seq && (uint32_t)(f.us-last_stats_us)>=1000000U) {
        last_stats_us=f.us;FocDqAudit_LogStats(&s);
    }
}
#endif
