/* Included by the opt-in protected diagnostic. All of this is task/command
 * context. No fast ISR logging, formatting, or new FOC filter. */
static uint8_t AngleChain_Off(void)
{
    return (uint8_t)(!(DRIVER_SD_GPIO_Port->ODR & DRIVER_SD_Pin) &&
        !(TIM1->BDTR & (TIM_BDTR_MOE|TIM_BDTR_AOE)) && !TIM1->CCER &&
        motor_control_mode==MOTOR_MODE_IDLE && cl_session.state==CL_READY &&
        !adc_fault && !foc_fault && !torque_diag.used);
}
__attribute__((optimize("Os")))
static int AngleChain_Command(const char *cmd,char *out,size_t size)
{
    if (strncmp(cmd,"MOTOR TEST ANGLE",sizeof("MOTOR TEST ANGLE")-1U)) return 0;
    if (!strcmp(cmd,"MOTOR TEST ANGLE BEGIN")) {
        uint32_t mask=__get_PRIMASK(); __disable_irq();
        uint8_t ok=(uint8_t)(AngleChain_Off() && ProtectedLoop_Ready() &&
            !angle_hand.active && !torque_diag.queued && !torque_diag.admitting);
        if (ok) FocAngleHand_Begin(&angle_hand,AS5047P_DmaNowUs());
        __set_PRIMASK(mask);
        snprintf(out,size,ok ? "OK ANGLE BEGIN OUTPUT_OFF=1" : "ERR 109 ANGLE_BEGIN_DENIED"); return 1;
    }
    if (!strcmp(cmd,"MOTOR TEST ANGLE END")) {
        uint32_t mask=__get_PRIMASK(); __disable_irq();
        int pass=0; uint8_t ok=(uint8_t)(AngleChain_Off() && angle_hand.active);
        if (ok) pass=FocAngleHand_End(&angle_hand);
        __set_PRIMASK(mask);
        if (!ok) snprintf(out,size,"ERR 109 ANGLE_END_DENIED");
        else snprintf(out,size,"OK ANGLE END PASS=%u SOFTWARE_CHAIN_ONLY=1",(unsigned)pass);
        return 1;
    }
    if (!strcmp(cmd,"MOTOR TEST ANGLE STATUS")) {
        uint32_t mask=__get_PRIMASK(); __disable_irq();
        uint32_t n=angle_hand.records,errors=angle_hand.errors;
        int32_t mc=angle_hand.mechanical_counts,lo=angle_hand.min_counts,hi=angle_hand.max_counts;
        float err=angle_hand.max_chain_error;
        uint8_t active=angle_hand.active,pass=angle_hand.passed,off=AngleChain_Off();
        __set_PRIMASK(mask);
        snprintf(out,size,"OK ANGLE ACTIVE=%u PASS=%u OFF=%u N=%lu ERR=%lu MC=%ld MIN=%ld MAX=%ld EERR_MDEG=%ld PP=10 DIR=-1 ZERO=10507",
            active,pass,off,(unsigned long)n,(unsigned long)errors,(long)mc,(long)lo,(long)hi,(long)(err*1000.0f)); return 1;
    }
    const char *prefix="MOTOR TEST ANGLE READ ";
    if (!strncmp(cmd,prefix,strlen(prefix))) {
        const char *p=cmd+strlen(prefix); uint32_t seq=0U; uint8_t valid=(uint8_t)(*p!=0);
        while (*p && valid) {
            if (*p<'0' || *p>'9' || seq>1000000U) { valid=0U; break; }
            seq=seq*10U+(uint32_t)(*p++-'0');
        }
        FocAngleHandFrame f={0}; uint32_t mask=__get_PRIMASK(); __disable_irq();
        uint32_t n=angle_hand.records;
        valid=(uint8_t)(valid && AngleChain_Off() && seq<n && n-seq<=ANGLE_HAND_ROWS);
        if (valid) f=angle_hand.rows[seq%ANGLE_HAND_ROWS];
        __set_PRIMASK(mask);
        if (valid && f.seq==seq) snprintf(out,size,
            "OK ANGLE ROW=%lu US=%lu RAW=%u MC=%ld MMDEG=%ld EMDEG=%ld WRMDEG=%ld",
            (unsigned long)f.seq,(unsigned long)f.us,f.raw,(long)f.mechanical_counts,
            (long)(f.mechanical_position_deg*1000.0f),(long)(f.electrical_unwrapped_deg*1000.0f),
            (long)(f.electrical_wrapped_rad*57295.7795131f));
        else snprintf(out,size,"ERR 109 ANGLE_ROW_MISSING");
        return 1;
    }
#if !defined(FOC_ANGLE_HAND_ONLY)
    if (!strcmp(cmd,"MOTOR TEST ANGLE OFFSET STATUS")) {
        snprintf(out,size,"OK ANGLE OFFSET IQ_MA=350 ID_MA=0 LEASE_US=400000 DEG=%ld USED=%u ACTIVE=%u HAND_PASS=%u",
            (long)torque_diag.offset_deg,torque_diag.used,torque_diag.active,angle_hand.passed); return 1;
    }
    uint32_t mask=__get_PRIMASK(); __disable_irq();
    uint8_t ready=(uint8_t)(AngleChain_Off() && ProtectedLoop_Ready() &&
        angle_hand.passed && angle_hand.finished && !angle_hand.active && !cl_session.used &&
        !Tightening_IsBusy() && !tightening_start_request && !tightening_stop_request);
    int accepted=FocTorqueChain_Queue(&torque_diag,cmd,ready);
    __set_PRIMASK(mask);
    snprintf(out,size,accepted ? "OK ANGLE OFFSET QUEUED MANUAL_ONE_SHOT=1" : "ERR 109 ANGLE_OFFSET_DENIED");
#else
    snprintf(out,size,"ERR 109 ANGLE_HAND_ONLY");
#endif
    return 1;
}
