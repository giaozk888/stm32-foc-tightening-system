/* Task-only, read-only protocol. No power, setpoint, mode or parameter setter. */
static int32_t MechanicalDob_Fixed(float value,float scale)
{
    float v=value*scale;
    if (!isfinite(v)) return 0;
    if (v>2147483000.f) return 2147483000;
    if (v< -2147483000.f) return -2147483000;
    return (int32_t)v;
}
#if defined(FOC_DOB_WARMUP_AB)
#include "dob_warmup_ab_binding.inc"
#endif
static uint8_t MechanicalDob_ObserverCommand(const char *cmd,char *out,size_t size)
{
#if defined(FOC_DOB_WARMUP_AB)
    if(DobWarmupAb_Command(cmd,out,size))return 1;
#endif
    const MechanicalNormalizedModel *m=&mechanical_dob_identified_model;
#if defined(FOC_DOB_RECOVERY_TIMING)
    if(!strcmp(cmd,"MOTOR TEST MECH DOB RECOVERY CFG")){
        snprintf(out,size,"OK DOBREC ABI=1 RECORDS=3 BYTES=48 PENDING=1 RESOLUTION_US=1000 READ=HALTED_RAM DEFAULT_TAU=3 WINDOW_MS=75");return 1;
    }
#endif
#if defined(FOC_DOB_SATURATION_CONTINUE)
    if(!strcmp(cmd,"MOTOR TEST MECH DOB SAT CFG")){
        snprintf(out,size,"OK DOBSAT V=1 EST_ON_LIMIT=1 FB_ON_LIMIT=0 INPUT_GATES=ORIGINAL HOLD_US=5000 ZERO_US=20000");return 1;
    }
    if(!strcmp(cmd,"MOTOR TEST MECH DOB SAT STATS")){
        snprintf(out,size,"OK DOBSAT N=%lu IQ=%lu V=%lu VALID=%lu RESET=%lu FB_BLOCK=%lu SKIP=%lu WARM=%lu",
            (unsigned long)dob_saturation_audit.samples,(unsigned long)dob_saturation_audit.iq_limited,
            (unsigned long)dob_saturation_audit.voltage_limited,(unsigned long)dob_saturation_audit.limited_valid,
            (unsigned long)dob_saturation_audit.input_resets,(unsigned long)dob_saturation_audit.feedback_blocks,
            (unsigned long)dob_saturation_audit.current_skips,(unsigned long)dob_saturation_audit.warmup_frames);return 1;
    }
#endif
#if defined(FOC_NORMAL_RUN_TRIP500)
    if(!strcmp(cmd,"MOTOR TEST MECH DOB LIMITS")){
        snprintf(out,size,"OK DOBLIMITS TARGET_RPM=%u GUARD_RPM=%u SPEED_TRIP_RPM=%lu IQ_LIMIT_MA=%lu TRAVEL_DEG=%u LEASE_US=%lu",
            FOC_RUNDOWN240_TARGET_RPM,CL_OVERSPEED_RPM,(unsigned long)SPEED_OVERSPEED_RPM,
            (unsigned long)(FOC_RUNDOWN240_IQ_LIMIT_A*1000.f),FOC_RUNDOWN240_MAX_TRAVEL_DEG,
            (unsigned long)CL_MAX_US);return 1;
    }
#endif
#if defined(FOC_DOB_TREND_SHADOW)
#if defined(FOC_DOB_TREND_WINDOW75)
    if(!strcmp(cmd,"MOTOR TEST MECH DOB WINDOW CFG")){
        snprintf(out,size,"OK DOBWINDOW WINDOW_MS=75 MIN_GOOD=45 MIN_SPAN_US=45000 TREND_TAU_US=100000 TREND_DWELL_US=80000 LEVEL_DWELL_US=30000");return 1;
    }
#endif
#if defined(FOC_DOB_TREND_CONTINUOUS)
    if(!strcmp(cmd,"MOTOR TEST MECH DOB TREND CFG")){
        snprintf(out,size,"OK TREND ABI=2 SHADOW=1 TAU_US=100000 DWELL_US=80000 RECORD_US=60000 POINTS=138 EVENTS=32 CONTINUOUS=1");return 1;
    }
    if(!strcmp(cmd,"MOTOR TEST MECH DOB TREND")){
        snprintf(out,size,"OK TREND ABI=2 FLAGS=%lu N=%lu RECORDS=%lu EVENTS=%lu RWRAP=%lu EWRAP=%lu LAST_US=%lu",
            (unsigned long)dob_trend_continuous.flags,(unsigned long)dob_trend_continuous.observations,
            (unsigned long)dob_trend_continuous.record_count,(unsigned long)dob_trend_continuous.event_count,
            (unsigned long)dob_trend_continuous.record_overflow,(unsigned long)dob_trend_continuous.event_dropped,
            (unsigned long)dob_trend_continuous.last_record_us);return 1;
    }
#else
    if(!strcmp(cmd,"MOTOR TEST MECH DOB TREND CFG")){
        snprintf(out,size,"OK TREND ABI=1 SHADOW=1 TAU_US=100000 DWELL_US=80000 SPAN_US=100000 GAP_US=20000 RECORD_US=8000 POINTS=144 PROXY_UA=10000");return 1;
    }
    if(!strcmp(cmd,"MOTOR TEST MECH DOB TREND")){
        snprintf(out,size,"OK TREND FLAGS=%lu N=%lu ARM_US=%lu RISE_US=%lu CONFIRM_US=%lu FALL_US=%lu RELEASE_US=%lu",
            (unsigned long)dob_trend_shadow.flags,(unsigned long)dob_trend_shadow.observations,
            (unsigned long)dob_trend_shadow.arm_us,(unsigned long)dob_trend_shadow.proxy_rise_us,
            (unsigned long)dob_trend_shadow.trend_rise_us,(unsigned long)dob_trend_shadow.proxy_fall_us,
            (unsigned long)dob_trend_shadow.trend_fall_us);return 1;
    }
#endif
#endif
#if defined(FOC_DOB_CONTACT20_OBSERVE10)
    if(!strcmp(cmd,"MOTOR TEST MECH DOB SPEEDS")){
        snprintf(out,size,"OK DOBSPEED CONTACT_RPM=20 OBS_MIN_MRPM=10000 FB_MIN_MRPM=20000 RAM_ONLY=1");return 1;
    }
#endif
#if defined(FOC_DOB_ID_TRACE)
    if(!strcmp(cmd,"MOTOR TEST MECH IDTRACE")){
#if defined(FOC_DOB_ID_PRE_LPF_QUALITY)
        snprintf(out,size,"OK IDTRACE V=7 PRE=16 DENSE=24 TAIL=32 TAIL_US=16000 STATE=%lu POST=%lu NT=%lu RESET=%lu FEEDBACK=0",
#elif defined(FOC_DOB_PERSISTENT_QUALITY)
        snprintf(out,size,"OK IDTRACE V=6 PRE=16 DENSE=32 TAIL=48 TAIL_US=16000 STATE=%lu POST=%lu NT=%lu RESET=%lu FEEDBACK=0",
#elif defined(FOC_DOB_RECOVERABLE_ADMISSION)
        snprintf(out,size,"OK IDTRACE V=5 PRE=16 DENSE=32 TAIL=48 TAIL_US=16000 STATE=%lu POST=%lu NT=%lu RESET=%lu FEEDBACK=0",
#elif defined(FOC_DOB_DIRECT_JUMP_REJECT)
        snprintf(out,size,"OK IDTRACE V=4 PRE=16 DENSE=32 TAIL=48 TAIL_US=4000 STATE=%lu POST=%lu NT=%lu RESET=%lu FEEDBACK=0",
#elif defined(FOC_DOB_ADMISSION_START_GUARD)
        snprintf(out,size,"OK IDTRACE V=3 PRE=16 DENSE=32 TAIL=48 TAIL_US=4000 STATE=%lu POST=%lu NT=%lu RESET=%lu FEEDBACK=0",
#elif defined(FOC_DOB_SPIKE_ADMISSION)
        snprintf(out,size,"OK IDTRACE V=2 PRE=32 DENSE=32 TAIL=128 TAIL_US=4000 STATE=%lu POST=%lu NT=%lu RESET=%lu FEEDBACK=0",
#else
        snprintf(out,size,"OK IDTRACE V=1 PRE=64 DENSE=64 TAIL=160 TAIL_US=4000 STATE=%lu POST=%lu NT=%lu RESET=%lu FEEDBACK=0",
#endif
            (unsigned long)dob_id_trace.state,(unsigned long)dob_id_trace.post_count,
            (unsigned long)dob_id_trace.tail_count,(unsigned long)dob_id_trace.reset_calls_total);return 1;
    }
#endif
#if defined(FOC_DOB_SPIKE_ADMISSION)
#if defined(FOC_DOB_ADMISSION_START_GUARD)
    if(!strcmp(cmd,"MOTOR TEST MECH DOB ADMIT ARM")){
        snprintf(out,size,"OK ADMIT ARM V=1 CONFIRM_US=50000 MIN_W_MRAD_S=%ld ARMED=%lu QUAL_US=%lu PRE_N=%lu ARM_US=%lu FEEDBACK=0",
            (long)MechanicalDob_Fixed(m->min_speed_rad_s,1e3f),
            (unsigned long)dob_current_admission.armed,(unsigned long)dob_current_admission.qualify_us,
            (unsigned long)dob_current_admission.prearm_samples,(unsigned long)dob_current_admission.arm_us);return 1;
    }
#endif
    if(!strcmp(cmd,"MOTOR TEST MECH DOB ADMIT CFG")){
#if defined(FOC_DOB_ID_PRE_LPF_QUALITY)
        snprintf(out,size,"OK ADMIT V=5 MODE=PREFILTER JUMP_UA=%ld CONFIRM=%u ID_MAX_UA=%ld ID_US=%u REF=TRUSTED GAP_US=%u LATCH=0 FEEDBACK=0",
            (long)MechanicalDob_Fixed(DOB_ADMIT_JUMP_A,1e6f),DOB_ADMIT_JUMP_CONFIRM_POINTS,
            (long)MechanicalDob_Fixed(DOB_MONITOR_MAX_FILTERED_ABS_ID_A,1e6f),DOB_ID_BAD_CONFIRM_US,
            DOB_ADMIT_RECOVERABLE_GAP_US);return 1;
#elif defined(FOC_DOB_PERSISTENT_QUALITY)
        snprintf(out,size,"OK ADMIT V=4 MODE=PERSIST JUMP_UA=%ld POINTS=%u ID_MAX_UA=%ld ID_US=%u REF=RAW GAP_US=%u LATCH=0 FEEDBACK=0",
            (long)MechanicalDob_Fixed(DOB_ADMIT_JUMP_A,1e6f),DOB_ADMIT_JUMP_CONFIRM_POINTS,
            (long)MechanicalDob_Fixed(DOB_MONITOR_MAX_FILTERED_ABS_ID_A,1e6f),DOB_ID_BAD_CONFIRM_US,
            DOB_ADMIT_RECOVERABLE_GAP_US);return 1;
#elif defined(FOC_DOB_RECOVERABLE_ADMISSION)
        snprintf(out,size,"OK ADMIT V=3 MODE=SKIP JUMP_UA=%ld ID_MAX_UA=%ld REF=RAW GAP_US=%u LATCH=0 FEEDBACK=0",
            (long)MechanicalDob_Fixed(DOB_ADMIT_JUMP_A,1e6f),
            (long)MechanicalDob_Fixed(DOB_MONITOR_MAX_FILTERED_ABS_ID_A,1e6f),DOB_ADMIT_RECOVERABLE_GAP_US);return 1;
#elif defined(FOC_DOB_DIRECT_JUMP_REJECT)
        snprintf(out,size,"OK ADMIT V=2 MODE=DIRECT JUMP_UA=%ld ID_MAX_UA=%ld REF=ACCEPTED GAP_US=%u CONSEC=%u WINDOW=%u MAX_HOLD=%u FEEDBACK=0",
            (long)MechanicalDob_Fixed(DOB_ADMIT_JUMP_A,1e6f),
            (long)MechanicalDob_Fixed(DOB_MONITOR_MAX_FILTERED_ABS_ID_A,1e6f),DOB_ADMIT_MAX_HOLD_US,
            DOB_ADMIT_MAX_CONSEC_HOLDS,DOB_ADMIT_WINDOW_SAMPLES,DOB_ADMIT_MAX_WINDOW_HOLDS);return 1;
#else
        snprintf(out,size,"OK ADMIT V=1 SHADOW=1 JUMP_UA=%ld RETURN_UA=%ld CONFIRM_UA=%ld GAP_US=%u CONSEC=%u WINDOW=%u MAX_HOLD=%u FEEDBACK=0",
            (long)MechanicalDob_Fixed(DOB_ADMIT_JUMP_A,1e6f),(long)MechanicalDob_Fixed(DOB_ADMIT_RETURN_A,1e6f),
            (long)MechanicalDob_Fixed(DOB_ADMIT_CONFIRM_A,1e6f),DOB_ADMIT_MAX_HOLD_US,
            DOB_ADMIT_MAX_CONSEC_HOLDS,DOB_ADMIT_WINDOW_SAMPLES,DOB_ADMIT_MAX_WINDOW_HOLDS);return 1;
#endif
    }
#if defined(FOC_DOB_RECOVERABLE_ADMISSION)
    if(!strcmp(cmd,"MOTOR TEST MECH DOB ADMIT GAPS")){
        snprintf(out,size,"OK ADMIT GAPS V=1 STALE=%lu RESET=%lu RECOVER=%lu GAP_US=%lu FEEDBACK=0",
            (unsigned long)dob_current_admission.gap_stale,(unsigned long)dob_current_admission.gap_resets,
            (unsigned long)dob_current_admission.recoveries,(unsigned long)dob_current_admission.accepted_gap_us);return 1;
    }
#endif
#if defined(FOC_DOB_PERSISTENT_QUALITY)
    if(!strcmp(cmd,"MOTOR TEST MECH DOB ADMIT PERSIST")){
        snprintf(out,size,"OK PERSIST V=1 RUN=%lu MAX_RUN=%lu PENDING=%lu ID_US=%lu ID_PEAK_US=%lu ID_BAD=%lu ID_ENTER=%lu ID_RECOVER=%lu FEEDBACK=0",
            (unsigned long)dob_current_admission.jump_run,(unsigned long)dob_current_admission.jump_max_run,
            (unsigned long)dob_current_admission.jump_pending_samples,(unsigned long)dob_current_admission.id_bad_us,
            (unsigned long)dob_current_admission.id_bad_peak_us,(unsigned long)dob_current_admission.id_bad_latched,
            (unsigned long)dob_current_admission.id_bad_entries,(unsigned long)dob_current_admission.id_bad_recoveries);return 1;
    }
#endif
#if defined(FOC_DOB_ID_PRE_LPF_QUALITY)
    if(!strcmp(cmd,"MOTOR TEST MECH DOB ADMIT QUALITY")){
        snprintf(out,size,"OK QUALITY V=1 WHY=%lu PENDING=%lu COHERENT=%lu RECOVER=%lu LEVEL=%lu SEED=%lu LPF_UPDATE=%lu FEEDBACK=0",
            (unsigned long)dob_current_admission.quality_reason,(unsigned long)dob_current_admission.pending,
            (unsigned long)dob_current_admission.jump_run,(unsigned long)dob_current_admission.quality_recoveries,
            (unsigned long)dob_current_admission.level_confirms,(unsigned long)dob_current_admission.seed_confirms,
            (unsigned long)dob_current_admission.filter_updated);return 1;
    }
#endif
    if(!strcmp(cmd,"MOTOR TEST MECH DOB ADMIT STATS")){
        snprintf(out,size,"OK ADMIT STATS V=1 N=%lu PASS=%lu SUS=%lu SPIKE=%lu STEP=%lu UNR=%lu HOLD=%lu EXIT=%lu FEEDBACK=0",
            (unsigned long)dob_current_admission.samples,(unsigned long)dob_current_admission.passed,
            (unsigned long)dob_current_admission.suspects,(unsigned long)dob_current_admission.isolated,
            (unsigned long)dob_current_admission.transitions,(unsigned long)dob_current_admission.unresolved,
            (unsigned long)dob_current_admission.held,(unsigned long)dob_current_admission.budget_exits);return 1;
    }
    if(!strcmp(cmd,"MOTOR TEST MECH DOB ADMIT")){
        snprintf(out,size,"OK ADMIT V=1 DEC=%lu BLOCK=%lu WHY=%lu N=%lu HOLD=%lu EXIT=%lu FEEDBACK=0",
            (unsigned long)dob_current_admission.decision,(unsigned long)dob_current_admission.blocked,
            (unsigned long)dob_current_admission.exit_reason,(unsigned long)dob_current_admission.samples,
            (unsigned long)dob_current_admission.held,
            (unsigned long)dob_current_admission.budget_exits);return 1;
    }
#endif
    if (!strcmp(cmd,"MOTOR TEST MECH DOB MODEL")) {
        snprintf(out,size,"OK DOB MODEL SHADOW=1 FEEDBACK=0 J_NA_S2_RAD=%ld B_NA_S_RAD=%ld IC_UA=%ld BIAS_UA=%ld BW_MRAD_S=%ld MIN_W_MRAD_S=%ld",
            (long)MechanicalDob_Fixed(m->j_over_kt,1e9f),(long)MechanicalDob_Fixed(m->b_over_kt,1e9f),
            (long)MechanicalDob_Fixed(m->coulomb_over_kt,1e6f),(long)MechanicalDob_Fixed(m->bias_a,1e6f),
            (long)MechanicalDob_Fixed(m->bandwidth_rad_s,1e3f),(long)MechanicalDob_Fixed(m->min_speed_rad_s,1e3f));return 1;
    }
    uint8_t adc=(uint8_t)!strcmp(cmd,"MOTOR TEST MECH DOB ADC");
    uint8_t stats=(uint8_t)!strcmp(cmd,"MOTOR TEST MECH DOB STATS");
    if (!adc && !stats && strcmp(cmd,"MOTOR TEST MECH DOB")) return 0;
    MechanicalDobMonitorView v;
    if (!MechanicalDobMonitor_Read(&mechanical_dob_monitor,&v)) {
        snprintf(out,size,"OK DOB SHADOW=1 FEEDBACK=0 LIVE=0 VALID=0 BUSY=1");return 1;
    }
    uint8_t live=(uint8_t)(cl_armed && !adc_fault && !foc_fault && cl_session.state==CL_RUNNING &&
        v.running && !v.frozen && AS5047P_DmaNowUs()-v.current.sample_us<=2000U);
    /* The actual protocol owner has a 192-byte reply buffer. Split readonly
     * views rather than growing that task's stack or silently truncating. */
    if (adc) {
        snprintf(out,size,"OK DOB ADC SHADOW=1 FEEDBACK=0 LIVE=%u VALID=%u US=%lu SEQ=%lu ADC_US=%lu PUB_US=%lu",
            live,(unsigned)(live && v.current.valid),(unsigned long)v.current.sample_us,
            (unsigned long)v.current.adc_seq,(unsigned long)v.current.adc_source_us,
            (unsigned long)v.current.adc_published_us);return 1;
    }
    if (stats) {
        snprintf(out,size,"OK DOB STATS SHADOW=1 FEEDBACK=0 LIVE=%u N=%lu GOOD=%lu REJECT=%lu MAX_US=%lu PEAK_UA=%ld POS_UA=%ld NEG_UA=%ld",
            live,(unsigned long)v.observations,(unsigned long)v.valid_samples,
            (unsigned long)v.rejected_samples,(unsigned long)v.max_compute_us,
            (long)MechanicalDob_Fixed(v.disturbance_abs_peak,1e6f),
            (long)MechanicalDob_Fixed(v.positive_mean,1e6f),
            (long)MechanicalDob_Fixed(v.negative_mean,1e6f));return 1;
    }
    snprintf(out,size,"OK DOB SHADOW=1 FEEDBACK=0 LIVE=%u VALID=%u ST=%lu US=%lu W_MRAD_S=%ld IQ_UA=%ld IQLP_UA=%ld ID_UA=%ld D_UA=%ld",
        live,(unsigned)(live && v.current.valid),(unsigned long)v.current.status,
        (unsigned long)v.current.sample_us,
        (long)MechanicalDob_Fixed(v.current.omega_rad_s,1e3f),(long)MechanicalDob_Fixed(v.current.iq_a,1e6f),
        (long)MechanicalDob_Fixed(v.current.iq_matched_a,1e6f),(long)MechanicalDob_Fixed(v.current.id_a,1e6f),
        (long)MechanicalDob_Fixed(v.current.disturbance_a,1e6f));
    return 1;
}

#if defined(FOC_DOB_FEEDBACK_CANDIDATE)
#include "dob_feedback_binding.inc"
#endif
static uint8_t MechanicalDob_Command(const char *cmd,char *out,size_t size)
{
#if defined(FOC_DOB_FEEDBACK_CANDIDATE)
    if(DobFeedback_Command(cmd,out,size))return 1;
#endif
    uint8_t handled=MechanicalDob_ObserverCommand(cmd,out,size);
#if defined(FOC_DOB_FEEDBACK_CANDIDATE)
    /* Existing shadow estimator remains read-only, but do not falsely report
     * FEEDBACK=0 when the separate candidate summing junction is enabled. */
    if(handled){char *tag=strstr(out,"FEEDBACK=0");if(tag)tag[9]=dob_feedback.enabled?'1':'0';}
#endif
    return handled;
}
