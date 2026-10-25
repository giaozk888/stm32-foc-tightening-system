/* A-only, included after the protected loop declarations. Single writer is
 * MotorControlTask; snapshots serialize tasks, not the high-priority ADC ISR.
 * ADC has no access to these diagnostics, only the existing foc_iq_ref_A. */
#ifndef SPEED_ACCEL_EFFECTIVE_KA
#define SPEED_ACCEL_EFFECTIVE_KA SPEED_ACCEL_FF_KA_A_PER_RPM_S
#endif
static void SpeedAccelFf_Reset(void)
{
    SpeedAccelFf_StatsReset(&speed_accel_ff_stats);
    speed_accel_ff_frame.valid=0U;
#if defined(FOC_MECHANICAL_IDENT_DIAG)
    Mechanical_Reset(&mechanical_capture);
#endif
#if defined(FOC_KA_FULL_DIAG)
    KaFull_Reset(&ka_full_diagnostic);
#endif
#if defined(FOC_KA_SYNC_DIAG)
    KaSync_Reset(&ka_sync_diagnostic);
#endif
#if defined(FOC_KA_IDENT_DIAG)
    KaIdent_Reset(&ka_identification);
#endif
#if defined(FOC_ACCEL_FF_AUDIT)
    SpeedAccelAudit_Reset(&speed_accel_audit);
#endif
#if defined(FOC_STARTUP_TIMESTAMPS_DIAG)
    StartupTimes_Reset(&startup_timestamps);
#endif
#if defined(FOC_SPEED_FRICTION_CANDIDATE)
    SpeedFriction_Reset();
#endif
}
static void SpeedAccelFf_Monitor(void)
{
#if defined(FOC_KA_SYNC_DIAG) || defined(FOC_KA_FULL_DIAG)
    /* Complete frozen short window is read from RAM after STOP. */
#elif defined(FOC_KA_IDENT_DIAG)
    static uint32_t generation,index;
    KaIdentFrame frame;uint8_t have=0U;
    taskENTER_CRITICAL();
    if (generation!=ka_identification.generation) {
        generation=ka_identification.generation;index=0U;
    }
    if (index<ka_identification.count) { frame=ka_identification.frames[index++];have=1U; }
    taskEXIT_CRITICAL();
    if (have) KaIdent_Log(&frame);
#elif defined(FOC_ACCEL_FF_AUDIT)
    /* Audit replaces duplicate FRC logs only in its separate build.
     * One complete binary frame is copied/logged per 10Hz Monitor wake. */
    static uint32_t generation,index;
#if defined(FOC_STARTUP_TIMESTAMPS_DIAG)
    static uint32_t startup_last_valid;
    StartupTimestamps startup_copy;uint8_t startup_have=0U;
#endif
    SpeedAccelAuditFrame frame;uint8_t have=0U;
    taskENTER_CRITICAL();
    if (generation!=speed_accel_audit.meta.generation) {
        generation=speed_accel_audit.meta.generation;index=0U;
#if defined(FOC_STARTUP_TIMESTAMPS_DIAG)
        startup_last_valid=0U;
#endif
    }
#if defined(FOC_STARTUP_TIMESTAMPS_DIAG)
    if (startup_timestamps.valid!=startup_last_valid) {
        startup_last_valid=startup_timestamps.valid;
        startup_copy=startup_timestamps;startup_have=1U;
    }
#endif
    if (index<speed_accel_audit.meta.trace_count) {
        frame=speed_accel_audit.frames[index++];have=1U;
    }
    taskEXIT_CRITICAL();
    if (have) SpeedAccelAudit_Log(&frame);
#if defined(FOC_STARTUP_TIMESTAMPS_DIAG)
    if (startup_have && startup_copy.valid) StartupTimes_Log(&startup_copy);
#endif
#else
#if defined(FOC_SPEED_FRICTION_CANDIDATE)
    SpeedFriction_Monitor(); /* Includes all acceleration FF fields; no duplicate logs. */
#else
    static uint32_t last_seq;
    SpeedAccelFfFrame f;
    taskENTER_CRITICAL(); f=speed_accel_ff_frame; taskEXIT_CRITICAL();
    if (f.valid && f.seq!=last_seq) { last_seq=f.seq; SpeedAccelFf_Log(&f); }
#endif
#endif
}
static uint8_t SpeedAccelFf_Command(const char *cmd,char *out,size_t size)
{
    if (strncmp(cmd,"MOTOR TEST FF ",14U)) return 0U;
#if defined(FOC_STARTUP_TIMESTAMPS_DIAG)
    if (!strcmp(cmd,"MOTOR TEST FF STARTUP")) {
        StartupTimestamps s;
        taskENTER_CRITICAL();s=startup_timestamps;taskEXIT_CRITICAL();
        snprintf(out,size,"OK STARTUP VALID=%lu T0_US=%lu TIQ_US=%lu TMOTION_US=%lu TSPEED_US=%lu TSTABLE_US=%lu",
            (unsigned long)s.valid,(unsigned long)s.t0_us,(unsigned long)s.t_iq_us,
            (unsigned long)s.t_motion_us,(unsigned long)s.t_speed_us,(unsigned long)s.t_stable_us);
        return 1U;
    }
#endif
#if defined(FOC_ACCEL_FF_AUDIT)
    uint8_t gain_command=(uint8_t)(!strncmp(cmd,"MOTOR TEST FF GAIN ",19U));
    if (gain_command) {
        int percent=SpeedAccelAudit_GainPercent(cmd+19U);
        if (percent<0) { snprintf(out,size,"ERR AFF GAIN");return 1U; }
        taskENTER_CRITICAL();
        if (Tightening_IsBusy() || tightening_start_request || tightening_stop_request ||
            motor_control_mode!=MOTOR_MODE_IDLE ||
            (DRIVER_SD_GPIO_Port->ODR & DRIVER_SD_Pin) ||
            (TIM1->BDTR & (TIM_BDTR_MOE|TIM_BDTR_AOE)) || TIM1->CCER) {
            taskEXIT_CRITICAL();
            snprintf(out,size,"ERR AFF BUSY_OR_OUTPUT_ENABLED");return 1U;
        }
        /* Absolute conservative Ka base, not cumulative scaling. No PI or gate writes. */
        speed_accel_audit_ka=0.0001875f*(float)percent/100.0f;
        SpeedAccelFf_Reset();
        taskEXIT_CRITICAL();
    }
#endif
    if (!strcmp(cmd,"MOTOR TEST FF ON") || !strcmp(cmd,"MOTOR TEST FF OFF")) {
        uint8_t enabled=(uint8_t)(!strcmp(cmd,"MOTOR TEST FF ON"));
        taskENTER_CRITICAL();
        if (Tightening_IsBusy() || tightening_start_request || tightening_stop_request ||
            motor_control_mode!=MOTOR_MODE_IDLE ||
            (DRIVER_SD_GPIO_Port->ODR & DRIVER_SD_Pin) ||
            (TIM1->BDTR & (TIM_BDTR_MOE|TIM_BDTR_AOE)) || TIM1->CCER) {
            taskEXIT_CRITICAL();
            snprintf(out,size,"ERR AFF BUSY_OR_OUTPUT_ENABLED"); return 1U;
        }
        speed_accel_ff_enabled=enabled;
        SpeedAccelFf_Reset();
        taskEXIT_CRITICAL();
    }
    SpeedAccelFfStats s;
    taskENTER_CRITICAL(); s=speed_accel_ff_stats; taskEXIT_CRITICAL();
    if (!strcmp(cmd,"MOTOR TEST FF METRICS")) {
        snprintf(out,size,"OK AFF N=%lu MAX_ERR_MRPM=%ld ACC_MAE_MRPM=%ld DEC_MAE_MRPM=%ld SEG=%lu",
            (unsigned long)s.samples,(long)(1000*s.max_error_rpm),
            s.accel_time_s>0 ? (long)(1000*s.accel_error_integral/s.accel_time_s) : -1L,
            s.decel_time_s>0 ? (long)(1000*s.decel_error_integral/s.decel_time_s) : -1L,
            (unsigned long)s.segment);
    } else if (!strcmp(cmd,"MOTOR TEST FF METRICS2")) {
        snprintf(out,size,"OK AFF OV_MRPM=%ld SETTLE_MS=%ld IQ_REF_PEAK_MA=%ld IQ_MEAS_PEAK_MA=%ld I_PEAK_MA=%ld SAT_MS=%lu SAT_RUN_MS=%lu",
            (long)(1000*s.overshoot_rpm),s.settled ? (long)(1000*s.settling_time_s) : -1L,
            (long)(1000*s.iq_peak_a),(long)(1000*s.iq_measured_peak_a),(long)(1000*s.integrator_peak_a),
            (unsigned long)(1000*s.saturation_s),(unsigned long)(1000*s.saturation_run_max_s));
    } else if (!strcmp(cmd,"MOTOR TEST FF STATUS") || !strcmp(cmd,"MOTOR TEST FF ON") ||
               !strcmp(cmd,"MOTOR TEST FF OFF")
#if defined(FOC_ACCEL_FF_AUDIT)
               || gain_command
#endif
               ) {
        snprintf(out,size,"OK AFF ON=%u KA_NA_PER_RPM_S=%lu ACCEL_MAX_RPM_S=%u FF_PEAK_UA=%lu TOKENIZED=1",
            speed_accel_ff_enabled,(unsigned long)(SPEED_ACCEL_EFFECTIVE_KA*1e9f+0.5f),
            (unsigned)SPEED_SCURVE_MAX_ACCEL_RPM_S,
            (unsigned long)(SPEED_ACCEL_EFFECTIVE_KA*SPEED_SCURVE_MAX_ACCEL_RPM_S*1e6f+0.5f));
    } else snprintf(out,size,"ERR AFF COMMAND");
    return 1U;
}
