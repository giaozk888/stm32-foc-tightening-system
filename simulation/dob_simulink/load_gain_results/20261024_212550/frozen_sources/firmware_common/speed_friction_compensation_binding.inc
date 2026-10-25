/* MotorControlTask owns evidence; MonitorTask is the only log producer. */
#ifndef SPEED_ACCEL_EFFECTIVE_KA
#define SPEED_ACCEL_EFFECTIVE_KA SPEED_ACCEL_FF_KA_A_PER_RPM_S
#endif
static void SpeedFriction_Reset(void)
{
    SpeedFriction_StatsReset(&speed_friction_stats);
    speed_friction_frame.control.valid=0;
}
#if !defined(FOC_ACCEL_FF_AUDIT) && !defined(FOC_KA_IDENT_DIAG) && !defined(FOC_KA_SYNC_DIAG) && !defined(FOC_KA_FULL_DIAG)
static void SpeedFriction_Monitor(void)
{
    static uint32_t last_seq;
    SpeedFrictionFrame f;
    taskENTER_CRITICAL(); f=speed_friction_frame; taskEXIT_CRITICAL();
    if (f.control.valid && f.control.seq!=last_seq) {
        last_seq=f.control.seq; SpeedFriction_Log(&f);
    }
}
#endif
static uint8_t SpeedFriction_Command(const char *cmd,char *out,size_t size)
{
    if (strncmp(cmd,"MOTOR TEST FRIC ",16U)) return 0;
    const char *arg=cmd+16U;
    if (!strcmp(arg,"ON") || !strcmp(arg,"OFF")) {
        uint8_t enabled=(uint8_t)(!strcmp(arg,"ON"));
        taskENTER_CRITICAL();
        if (Tightening_IsBusy() || tightening_start_request || tightening_stop_request ||
            motor_control_mode!=MOTOR_MODE_IDLE || (DRIVER_SD_GPIO_Port->ODR & DRIVER_SD_Pin) ||
            (TIM1->BDTR & (TIM_BDTR_MOE|TIM_BDTR_AOE)) || TIM1->CCER) {
            taskEXIT_CRITICAL(); snprintf(out,size,"ERR FRC BUSY_OR_OUTPUT_ENABLED"); return 1;
        }
        speed_friction_enabled=enabled;
        SpeedAccelFf_Reset(); /* Evidence only: never re-arms a lease or resets PI. */
        taskEXIT_CRITICAL();
    }
    SpeedFrictionStats s;
    taskENTER_CRITICAL(); s=speed_friction_stats; taskEXIT_CRITICAL();
    if (!strcmp(arg,"ON") || !strcmp(arg,"OFF") || !strcmp(arg,"STATUS")) {
        snprintf(out,size,"OK FRC ON=%u I_UA=%lu DB_MRPM=%lu FF_ON=%u KA_NA_PER_RPM_S=%lu TOKENIZED=1",
            speed_friction_enabled,(unsigned long)(SPEED_FRICTION_I_A*1e6f+.5f),
            (unsigned long)(SPEED_FRICTION_DEADBAND_RPM*1000+.5f),speed_accel_ff_enabled,
            (unsigned long)(SPEED_ACCEL_EFFECTIVE_KA*1e9f+.5f));
    } else {
        uint8_t second=(uint8_t)(!strncmp(arg,"METRICS2 ",9U));
        const char *dir=second ? arg+9U : !strncmp(arg,"METRICS ",8U) ? arg+8U : "";
        if (strcmp(dir,"POS") && strcmp(dir,"NEG")) {
            snprintf(out,size,"ERR FRC COMMAND"); return 1;
        }
        const SpeedFrictionDirectionStats *d=!strcmp(dir,"POS") ? &s.positive : &s.negative;
        if (!second) snprintf(out,size,
            "OK FRC DIR=%s N=%lu START_MS=%ld LOW_MAE_MRPM=%ld CRUISE_MAE_MRPM=%ld",
            dir,(unsigned long)d->samples,d->start_delay_s>=0 ? (long)(1000*d->start_delay_s) : -1L,
            d->low_time_s>0 ? (long)(1000*d->low_error_integral/d->low_time_s) : -1L,
            d->cruise_time_s>0 ? (long)(1000*d->cruise_error_integral/d->cruise_time_s) : -1L);
        else snprintf(out,size,
            "OK FRC DIR=%s I_PEAK_MA=%ld PI_PEAK_MA=%ld IQ_REF_PEAK_MA=%ld IQ_MEAS_PEAK_MA=%ld MEAN_MRPM=%ld WRONG_MS=%lu",
            dir,(long)(1000*d->integrator_peak_a),(long)(1000*d->pi_peak_a),
            (long)(1000*d->iq_peak_a),(long)(1000*d->iq_measured_peak_a),
            d->elapsed_s>0 ? (long)(1000*d->speed_integral/d->elapsed_s) : 0L,
            (unsigned long)(1000*d->wrong_direction_time_s));
    }
    return 1;
}
