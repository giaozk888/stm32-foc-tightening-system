/* Included only by the opt-in startup-evidence candidate. Never at 20 kHz. */
#include "foc_startup_trace.h"
static FocStartupTrace cl_startup;
#if defined(FOC_BREAKAWAY_FIVE_SECOND) || defined(FOC_TORQUE350_FIVE_SECOND) || defined(FOC_TORQUE450_FIVE_SECOND) || (defined(FOC_ANGLE_CHAIN_DIAG) && !defined(FOC_ANGLE_HAND_ONLY))
static FocBreakawayMotion breakaway_motion;
#endif
#if defined(FOC_RUNDOWN_DIAGNOSTIC)
#include "foc_pwm_write_probe.h"
extern FocPwmWriteProbe foc_pwm_write_profile;
static void ProtectedLoop_RundownFields(FocStartupFrame *f);
#endif
#if defined(FOC_BREAKAWAY_FIVE_SECOND) || defined(FOC_TORQUE350_FIVE_SECOND) || defined(FOC_TORQUE450_FIVE_SECOND) || (defined(FOC_ANGLE_CHAIN_DIAG) && !defined(FOC_ANGLE_HAND_ONLY))
__attribute__((optimize("Os")))
#endif
static FocStartupFrame ProtectedLoop_StartupFrame(uint32_t now)
{
    FocStartupFrame f={.us=now,.adc_seq=cl_seq,
        .encoder_us=encoder_dma_cursor.sample_us,.angle=encoder_raw,
        .u=cl_last_u,.v=cl_last_v,.ref=speed_ref_rpm,
        .instant=encoder_rpm_instant,.speed=encoder_speed_rpm,
        .iq_ref=foc_iq_ref_A,.id=foc_id_A,.iq=foc_iq_A,
        .vd=foc_vd_V,.vq=foc_vq_V,.int_d=foc_int_d_V,.int_q=foc_int_q_V};
#if defined(FOC_RUNDOWN_DIAGNOSTIC)
    ProtectedLoop_RundownFields(&f);
#endif
    return f;
}
#if defined(FOC_RUNDOWN_DIAGNOSTIC)
/* Caller already holds the existing trace critical section. CCR readback is
 * the last software-written PRELOAD value, NOT proof of pin/gate output or
 * an independently observed active latch. Pipeline itself stays untouched. */
#if defined(FOC_BREAKAWAY_FIVE_SECOND) || defined(FOC_TORQUE350_FIVE_SECOND) || defined(FOC_TORQUE450_FIVE_SECOND) || (defined(FOC_ANGLE_CHAIN_DIAG) && !defined(FOC_ANGLE_HAND_ONLY))
__attribute__((optimize("Os")))
#endif
static void ProtectedLoop_RundownFields(FocStartupFrame *f)
{
    f->detect=encoder_speed_detect_rpm; f->iq_error=f->iq_ref-f->iq;
    f->command=TIGHTEN_DIRECTION*(float)recipe_state.params.rundown_rpm;
#if defined(FOC_SPEED_DYNAMIC_DIAG)
    f->command=(float)CL_SPEED_RPM;
#elif defined(FOC_TORQUE_CHAIN_DIAG)
    f->command=0.0f; /* IQ mode has no speed command; don't report recipe rpm. */
#endif
    f->mechanical_angle=encoder_position_deg;
    f->electrical_angle=encoder_theta_e; f->predicted_angle=encoder_theta_e_pred;
    f->encoder_delta=rundown_encoder_delta; f->encoder_dt_us=rundown_encoder_dt_us;
    f->pending_seq=cl_pwm_pending.source_seq;
    f->pending_ccr[0]=cl_pwm_pending.ccr[0];
    f->pending_ccr[1]=cl_pwm_pending.ccr[1];
    f->pending_ccr[2]=cl_pwm_pending.ccr[2];
    f->applied_ccr[0]=(uint16_t)TIM1->CCR1;
    f->applied_ccr[1]=(uint16_t)TIM1->CCR2;
    f->applied_ccr[2]=(uint16_t)TIM1->CCR3;
    f->commit_count=foc_pwm_write_profile.writes;
#if defined(FOC_TORQUE_CHAIN_DIAG) && !FOC_HEAVY_PROFILE_ENABLE
    f->commit_count=foc_pwm_write_profile.points; /* Light reducer actual writes. */
#endif
    f->validator_state=cl_safety.validation.state;
    f->current_path=cl_current_path;
    f->reserved=encoder_speed_glitch_streak;
    f->encoder_valid=encoder_valid; f->pending_valid=cl_pwm_pending.valid;
    f->rundown_armed=tightening_rundown.state;
    f->contact_candidate=tightening_contact_condition;
    f->state=(uint8_t)tightening_test_stage; f->mode=(uint8_t)motor_control_mode;
    f->gates=(uint8_t)(((TIM1->BDTR & TIM_BDTR_MOE)!=0U) |
        (((DRIVER_SD_GPIO_Port->ODR & DRIVER_SD_Pin)!=0U)<<1U));
    f->voltage_saturated=(uint8_t)(f->vd*f->vd+f->vq*f->vq>=
        0.99f*0.99f*FOC_VOLTAGE_LIMIT_V*FOC_VOLTAGE_LIMIT_V);
}
static void ProtectedLoop_RundownEnd(void)
{
#if defined(FOC_TORQUE_CHAIN_DIAG)
    if (torque_diag.active) return;
#endif
    if (cl_startup.fault_valid || cl_startup.terminal_valid || !cl_startup.total ||
        tightening_test_stage==TIGHTEN_STATE_RUNDOWN) return;
    uint32_t mask=__get_PRIMASK(); __disable_irq();
    FocStartupFrame f=ProtectedLoop_StartupFrame(AS5047P_DmaNowUs());
    FocStartup_RundownEnd(&cl_startup,f);
    __set_PRIMASK(mask);
}
#endif
#if defined(FOC_BREAKAWAY_FIVE_SECOND) || defined(FOC_TORQUE350_FIVE_SECOND) || defined(FOC_TORQUE450_FIVE_SECOND) || (defined(FOC_ANGLE_CHAIN_DIAG) && !defined(FOC_ANGLE_HAND_ONLY))
__attribute__((optimize("Os")))
#endif
static void ProtectedLoop_StartupPush(void)
{
#if defined(FOC_ANGLE_CHAIN_DIAG)
    /* Accepted task sample only. No ADC ISR work and no output writes. */
    if (angle_hand.active) FocAngleHand_Observe(&angle_hand,AS5047P_DmaNowUs(),
        encoder_raw,encoder_theta_e,encoder_position_deg,
        (uint8_t)(!(DRIVER_SD_GPIO_Port->ODR & DRIVER_SD_Pin) &&
            !(TIM1->BDTR & (TIM_BDTR_MOE|TIM_BDTR_AOE)) && !TIM1->CCER),
        (uint8_t)(encoder_valid && !encoder_speed_glitch_streak));
#endif
#if defined(FOC_BREAKAWAY_FIVE_SECOND) || defined(FOC_TORQUE350_FIVE_SECOND) || defined(FOC_TORQUE450_FIVE_SECOND) || (defined(FOC_ANGLE_CHAIN_DIAG) && !defined(FOC_ANGLE_HAND_ONLY))
    /* Called by the existing fresh-encoder 1kHz task, with IRQs enabled.
     * No copying/formatting in the fast ADC ISR or masked trace section. */
    if (torque_diag.active && cl_session.state==CL_RUNNING) {
        FocBreakaway_Observe(&breakaway_motion,AS5047P_DmaNowUs()-cl_session.start_us,
            encoder_raw,torque_diag.sign,
            (uint8_t)(motor_control_mode==MOTOR_MODE_IQ && foc_id_ref_A==0.0f &&
                fabsf(foc_iq_ref_A-(float)torque_diag.sign*torque_diag.iq_mA*0.001f)<0.000001f),
            (uint8_t)((TIM1->BDTR & TIM_BDTR_MOE) && (DRIVER_SD_GPIO_Port->ODR & DRIVER_SD_Pin)),
            (uint8_t)(encoder_valid && !encoder_speed_glitch_streak));
    }
#endif
#if defined(FOC_RUNDOWN_DIAGNOSTIC)
#if defined(FOC_TORQUE_CHAIN_DIAG)
    if (!torque_diag.active || !cl_startup.active ||
#else
    if (tightening_test_stage!=TIGHTEN_STATE_RUNDOWN || !cl_startup.active ||
#endif
        cl_startup.frozen || cl_startup.total>=FOC_STARTUP_ROWS) return;
    uint32_t now=AS5047P_DmaNowUs();
    if (cl_startup.total && now-cl_startup.start_us-
        cl_startup.rows[cl_startup.total-1U].us<FOC_STARTUP_PERIOD_US) return;
#endif
    uint32_t mask=__get_PRIMASK(); __disable_irq();
    if (cl_session.state==CL_RUNNING && cl_startup.active)
#if defined(FOC_RUNDOWN_DIAGNOSTIC)
    {
        FocStartupFrame f=ProtectedLoop_StartupFrame(AS5047P_DmaNowUs());
        FocStartup_Push(&cl_startup,f);
    }
#else
        FocStartup_Push(&cl_startup,ProtectedLoop_StartupFrame(AS5047P_DmaNowUs()));
#endif
    __set_PRIMASK(mask);
}
static int ProtectedLoop_StartupCommand(const char *cmd,char *out,size_t size)
{
#if defined(FOC_RUNDOWN_DIAGNOSTIC)
    /* Extended schema is binary-only. Decode with the matching ELF and the
     * offline Python tool, never print/transfer this buffer during motion. */
    if (strncmp(cmd,"MOTOR TEST STARTUP",18U)) return 0;
#if defined(FOC_TORQUE_CHAIN_DIAG)
#if defined(FOC_ANGLE_CHAIN_DIAG)
    snprintf(out,size,"OK STARTUP SCHEMA=2 BINARY_ONLY=1 ROWS=" FOC_STARTUP_ROWS_TEXT " PERIOD_US=12000 BYTES=%lu",
#elif defined(FOC_BREAKAWAY_FIVE_SECOND) || defined(FOC_SPEED_DYNAMIC_DIAG) || defined(FOC_TORQUE350_FIVE_SECOND) || defined(FOC_TORQUE450_FIVE_SECOND)
    snprintf(out,size,"OK STARTUP SCHEMA=2 BINARY_ONLY=1 ROWS=" FOC_STARTUP_ROWS_TEXT " PERIOD_US=200000 BYTES=%lu",
#else
    snprintf(out,size,"OK STARTUP SCHEMA=2 BINARY_ONLY=1 ROWS=" FOC_STARTUP_ROWS_TEXT " PERIOD_US=8000 BYTES=%lu",
#endif
#else
    snprintf(out,size,"OK STARTUP SCHEMA=2 BINARY_ONLY=1 ROWS=" FOC_STARTUP_ROWS_TEXT " PERIOD_US=50000 BYTES=%lu",
#endif
        (unsigned long)sizeof cl_startup);
    return 1;
#else
    const char *prefix="MOTOR TEST STARTUP";
    if (strncmp(cmd,prefix,strlen(prefix))) return 0;
    if (!strcmp(cmd,"MOTOR TEST STARTUP CONFIG")) {
        snprintf(out,size,"OK STARTUP CONFIG ENABLED=1 ROWS=" FOC_STARTUP_ROWS_TEXT " FIRST_CAUSE=1 BYTES=%lu",
            (unsigned long)sizeof cl_startup); return 1;
    }
    /* No live transfer/formatting while bridge is enabled. A frozen trace
     * is immutable until reset, so no large memcpy under PRIMASK is needed. */
    if (!cl_startup.frozen) {
        snprintf(out,size,"ERR 109 STARTUP_NOT_FROZEN"); return 1;
    }
    if (!strcmp(cmd,prefix)) {
        snprintf(out,size,"OK STARTUP N=%lu TOTAL=%lu FROZEN=1 FAULT=%u FIRST_FLAGS=%lu OFF_US=%lu ORDER=REF,INST,CTRL;IQREF,ID,IQ;VD,VQ;INTD,INTQ",
            (unsigned long)FocStartup_Count(&cl_startup),(unsigned long)cl_startup.total,
            cl_startup.fault_valid,(unsigned long)cl_startup.first_flags,
            (unsigned long)cl_startup.first_off_us); return 1;
    }
    if (!strcmp(cmd,"MOTOR TEST STARTUP FAULT") && cl_startup.fault_valid) {
        FocStartup_Format(&cl_startup.fault,out,(uint32_t)size); return 1;
    }
    const char *frame_prefix="MOTOR TEST STARTUP FRAME ";
    const char *digit=cmd;
    uint32_t index=0U; int valid=0; FocStartupFrame row;
    if (!strncmp(cmd,frame_prefix,strlen(frame_prefix))) {
        digit=cmd+strlen(frame_prefix);
        valid=*digit!='\0';
        while (*digit) {
            if (*digit<'0' || *digit>'9' || index>=FOC_STARTUP_ROWS) { valid=0; break; }
            index=index*10U+(uint32_t)(*digit++-'0');
        }
    }
    if (valid && FocStartup_Get(&cl_startup,index,&row))
        FocStartup_Format(&row,out,(uint32_t)size);
    else snprintf(out,size,"ERR 109 STARTUP_FRAME");
    return 1;
#endif
}
