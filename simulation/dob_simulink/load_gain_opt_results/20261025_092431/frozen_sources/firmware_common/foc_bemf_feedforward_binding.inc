/* Task-only integer wire format; no formatting/log calls in the ADC ISR. */
static int32_t BemfWire_Scaled(float value,float scale)
{
    float x=value*scale;
    if (!isfinite(x) || x < -2147483648.0f || x >= 2147483648.0f)
        return INT32_MIN;
    return (int32_t)x;
}
static uint8_t Bemf_Command(const char *cmd,char *out,size_t size)
{
    if (strncmp(cmd,"MOTOR TEST BEMF ",16U)) return 0U;
    const char *arg=cmd+16U;
    uint8_t toggle=(uint8_t)(!strcmp(arg,"ON") || !strcmp(arg,"OFF"));
#if defined(FOC_BEMF_GAIN_DIAG)
    uint8_t change_gain=0U;
    uint32_t requested_gain=0U;
    if (!strncmp(arg,"GAIN ",5U)) {
        const char *n=arg+5U;
        if (!strcmp(n,"0")) requested_gain=0U;
        else if (!strcmp(n,"25")) requested_gain=25U;
        else if (!strcmp(n,"50")) requested_gain=50U;
        else if (!strcmp(n,"75")) requested_gain=75U;
        else if (!strcmp(n,"100")) requested_gain=100U;
        else {snprintf(out,size,"ERR BEMF GAIN_RANGE");return 1U;}
        change_gain=1U;
    }
    if (!toggle && !change_gain && strcmp(arg,"STATUS") && strcmp(arg,"VOLTAGE")) {
#else
    if (!toggle && strcmp(arg,"STATUS") && strcmp(arg,"VOLTAGE")) {
#endif
        snprintf(out,size,"ERR BEMF COMMAND"); return 1U;
    }
    uint32_t mask=__get_PRIMASK(); __disable_irq();
#if defined(FOC_BEMF_GAIN_DIAG)
    if (toggle || change_gain) {
#else
    if (toggle) {
#endif
        if (cl_session.state==CL_RUNNING || Tightening_IsBusy() ||
            tightening_start_request || tightening_stop_request ||
            motor_control_mode!=MOTOR_MODE_IDLE ||
            (DRIVER_SD_GPIO_Port->ODR & DRIVER_SD_Pin) ||
            (TIM1->BDTR & (TIM_BDTR_MOE|TIM_BDTR_AOE)) || TIM1->CCER) {
            __set_PRIMASK(mask);
            snprintf(out,size,"ERR BEMF BUSY_OR_OUTPUT_ENABLED"); return 1U;
        }
        if (!strcmp(arg,"ON") && !FocBemf_Configured()) {
            __set_PRIMASK(mask);
            snprintf(out,size,"ERR BEMF UNCALIBRATED_PSI"); return 1U;
        }
#if defined(FOC_BEMF_GAIN_DIAG)
        if (change_gain) bemf_gain_percent=requested_gain;
        else
#endif
        bemf_enabled=(uint8_t)(!strcmp(arg,"ON"));
        bemf_frame.valid=0U;
    }
    FocBemfFrame f=bemf_frame;
    uint8_t enabled=bemf_enabled;
#if defined(FOC_BEMF_GAIN_DIAG)
    uint32_t gain=bemf_gain_percent;
#endif
    __set_PRIMASK(mask);
    if (!strcmp(arg,"VOLTAGE")) {
        snprintf(out,size,"OK BEMF VALID=%lu SEQ=%lu US=%lu ON=%lu SAT=%lu WE_MRAD_S=%ld ID_UA=%ld IQ_UA=%ld VD_PI_UV=%ld VQ_PI_UV=%ld VQ_FF_UV=%ld VD_UV=%ld VQ_UV=%ld",
            (unsigned long)f.valid,(unsigned long)f.seq,(unsigned long)f.source_us,
            (unsigned long)f.enabled,(unsigned long)f.saturated,
            (long)BemfWire_Scaled(f.omega_e,1e3f),(long)BemfWire_Scaled(f.id,1e6f),
            (long)BemfWire_Scaled(f.iq,1e6f),(long)BemfWire_Scaled(f.vd_pi,1e6f),
            (long)BemfWire_Scaled(f.vq_pi,1e6f),(long)BemfWire_Scaled(f.vq_ff,1e6f),
            (long)BemfWire_Scaled(f.vd,1e6f),(long)BemfWire_Scaled(f.vq,1e6f));
    } else {
#if defined(FOC_BEMF_GAIN_DIAG)
        snprintf(out,size,"OK BEMF ON=%u CONFIGURED=%u PSI_NWB=%ld VALID=%lu SEQ=%lu DQ_CROSS=0 GAIN_PCT=%lu EFFECTIVE_PSI_NWB=%ld",
            enabled,(unsigned)FocBemf_Configured(),(long)BemfWire_Scaled(FOC_BEMF_PSI_WB,1e9f),
            (unsigned long)f.valid,(unsigned long)f.seq,(unsigned long)gain,
            (long)BemfWire_Scaled(FOC_BEMF_PSI_WB*(float)gain*0.01f,1e9f));
#else
        snprintf(out,size,"OK BEMF ON=%u CONFIGURED=%u PSI_NWB=%ld VALID=%lu SEQ=%lu DQ_CROSS=0",
            enabled,(unsigned)FocBemf_Configured(),(long)BemfWire_Scaled(FOC_BEMF_PSI_WB,1e9f),
            (unsigned long)f.valid,(unsigned long)f.seq);
#endif
    }
    return 1U;
}
