/* Included by APP A/B after application variables/prototypes, before bindings.
 * Diagnostic only: no command, mode change, threshold or hardware access. */
static volatile FocFaultSnapshot foc_fault_snapshot;
static volatile uint32_t current_hold_total;
static FocHoldWindow current_hold_window;
static uint32_t fault_snapshot_print_index;
#if defined(FOC_PROTECTED_CLOSED_LOOP) || defined(FOC_FEEDBACK_SAFETY_BINDING)
static void FaultDiag_FillProtected(volatile FocFaultSnapshot *s);
#endif
#if defined(FOC_FAST_CURRENT_REJECT)
static uint32_t FaultDiag_CurrentSamples(void);
#endif

__attribute__((optimize("Oz"),noinline,cold))
static void FaultDiag_CapturePacked(uint32_t domain_reason,
    FocTimeoutReason timeout, uint32_t elapsed_ms, uint32_t limit)
{
    uint32_t mask=__get_PRIMASK(); __disable_irq();
    if (foc_fault_snapshot.valid) { __set_PRIMASK(mask); return; }
#if defined(FOC_OUTER_OBSERVE_AFTER_ACK)
    /* Two integer stores inside the EXISTING first-fault critical section.
     * No scan, clock read, formatting, watchdog write or extra IRQ mask. */
    outer_completion_trace.fault_phase=outer_completion_trace.current.phase;
    outer_completion_trace.frozen=1U;
#endif
    volatile FocFaultSnapshot *s=&foc_fault_snapshot;
    s->timestamp_ms=HAL_GetTick();
    s->domain=domain_reason&255U; s->fault_reason=domain_reason>>8;
    s->timeout_reason=(uint32_t)timeout;
    s->motor_mode=(uint32_t)motor_control_mode;
    s->tightening_state=(uint32_t)tightening_test_stage;
    s->state_elapsed_ms=tightening_test_elapsed_ms;
    if (timeout!=FOC_TO_NONE && limit) {
        s->timeout.reason=timeout;
        s->timeout.elapsed_us=elapsed_ms*1000U;
        s->timeout.limit_us=limit*1000U;
    }
    s->position_deg=encoder_position_deg; s->position_target_deg=position_target_deg;
    s->position_error_deg=position_error_deg;
    s->speed_raw_rpm=encoder_rpm_instant; s->speed_filtered_rpm=encoder_speed_rpm;
    s->speed_command_rpm=speed_ref_rpm;
    s->iq_ref_A=foc_iq_ref_A; s->iq_measured_A=foc_iq_A; s->id_measured_A=foc_id_A;
    s->stall_elapsed_s=stall_timer_s; s->contact_candidate_ms=tightening_contact_candidate_ms;
    s->encoder_valid=encoder_valid; s->encoder_errors=encoder_error_count;
    s->adc_sample_count=injected_seq_count; s->foc_exec_count=foc_control_count;
    s->current_hold_total=current_hold_total;
    /* Fixed 16-byte copy, inside the writer critical section. No published
     * reader exists until valid+DMB below; do not turn this into a scan. */
    __builtin_memcpy((void *)&s->hold_window_count,&current_hold_window.count,16U);
#if defined(FOC_PROTECTED_CLOSED_LOOP) || defined(FOC_FEEDBACK_SAFETY_BINDING)
    FaultDiag_FillProtected(s);
#endif
    __DMB(); s->valid=1U; /* One serialized publication, never overwritten. */
    __set_PRIMASK(mask);
}

static void FaultDiag_Clear(void)
{
    uint32_t mask=__get_PRIMASK(); __disable_irq();
    foc_fault_snapshot=(FocFaultSnapshot){0}; __DMB();
    fault_snapshot_print_index=0U;
    __set_PRIMASK(mask);
}

__attribute__((noinline,cold,optimize("Oz")))
static void FaultDiag_Motor(uint32_t reason)
{ FaultDiag_Capture(FOC_DIAG_MOTOR,reason,FOC_TO_NONE,tightening_test_elapsed_ms,0U); }

/* No float formatting/newlib float printf. Native floats retained in RAM;
 * safe fixed-unit conversion and UART queueing occur ONLY in task context. */
/* Packed names follow EVERY 32-bit member after valid, including timeout.reason.
 * This avoids a pointer/offset table in the nearly full 224 KiB APP slot.
 * Layout assertions and host tests bind this schema to the RAM structure. */
static const char fault_diag_labels[]=
    "t_ms|DOM|FAULT_REASON|TO|MODE|STATE|"
    "STATE_MS|POS|PTGT|PERR|SPD_RAW|"
    "SPD_FILT|SPD_CMD|IqRef|Iq|Id|STALL|CONTACT|"
    "ENC|ENC_ERR|CUR_STATE|"
    "SUS|SPIKE|TRANS|UNRES|RUN|MAXRUN|"
    "MAX_CYC|N_CYC|S_CYC|U_CYC|"
    "D_MISS|ADC_N|FOC_N|hold_total|hold_n|"
    "hold_max|hold_ppt|hold_ms|"
    "CUR_OK|FLAGS|TO_ID|NOW_US|REF_US|"
    "DT_US|MAX_US|LAST_US|PEND_US|PEND|MISS|";
_Static_assert(sizeof(float)==4U && offsetof(FocFaultSnapshot,position_deg)==32U &&
    offsetof(FocFaultSnapshot,contact_candidate_ms)==72U &&
    sizeof(FocFaultSnapshot)==204U,"Update diagnostic word schema with RAM layout");
static const char fault_timeout_names[]=
    "NONE|CUR_FIRST|CUR_SAMPLE|CUR_CONFIRM|ADC_GUARD|ADC_CHAIN|FOC_CHAIN|OUTER|"
    "ENC_XFER|ENC_AGE|ENC_CTRL|ENC_SCHED|RUNDOWN|STOP_SETTLE|STALL_POS|STALL_SPD|"
    "ZERO_CAL|ENC_DT|COMPUTE|BRIDGE_US|BRIDGE_N|WALL|LEASE|UNKNOWN|";

__attribute__((optimize("Oz"),noinline))
static void FaultDiag_Monitor(void)
{
    uint32_t mask=__get_PRIMASK(); __disable_irq();
    uint32_t holds=current_hold_total;
    uint32_t samples=injected_seq_count;
#if defined(FOC_FAST_CURRENT_REJECT)
    samples=FaultDiag_CurrentSamples();
#endif
    __set_PRIMASK(mask);
    /* Window bookkeeping is not shared halfway through an ISR capture. */
    FocHoldWindow next=current_hold_window;
    FocHoldWindow_Update(&next,HAL_GetTick(),holds,samples);
    mask=__get_PRIMASK(); __disable_irq(); current_hold_window=next; __set_PRIMASK(mask);
    if (!foc_fault_snapshot.valid) return;
    __DMB();
    char line[112];
    if (!fault_snapshot_print_index) {
        uint32_t r=foc_fault_snapshot.timeout_reason;
        const char *name=fault_timeout_names;
        if (r>FOC_TO_UNKNOWN) r=FOC_TO_UNKNOWN;
        while (r--) name=strchr(name,'|')+1;
        if (!UART_SendReliableFormatted(line,sizeof(line),
            "FAULT SNAPSHOT TIMEOUT_SUBREASON=%.*s DRV_FAULT=NA\r\n",
            (int)(strchr(name,'|')-name),name)) return;
        fault_snapshot_print_index=1U;
    }
    const uint32_t n=sizeof(FocFaultSnapshot)/4U-1U;
    const char *label=fault_diag_labels;
    for (uint32_t i=1U;i<fault_snapshot_print_index && i<=n;++i)
        label=strchr(label,'|')+1; /* Task-only resume; never runs in fault ISR. */
    while (fault_snapshot_print_index<=n) {
        uint32_t word=fault_snapshot_print_index;
        const volatile uint8_t *p=(const volatile uint8_t *)&foc_fault_snapshot+word*4U;
        const char *end=strchr(label,'|');
        int length=(int)(end-label);
        uint8_t sent;
        if (word>=8U && word<=17U) {
            float x=*(const volatile float *)p;
            if (!(x>= -2147483.0f && x<=2147483.0f))
                sent=UART_SendReliableFormatted(line,sizeof(line),"%.*s=INVALID\r\n",length,label);
            else sent=UART_SendReliableFormatted(line,sizeof(line),"%.*s=%ld\r\n",length,label,(long)(x*1000.0f));
        } else sent=UART_SendReliableFormatted(line,sizeof(line),"%.*s=%lu\r\n",length,label,
            (unsigned long)*(const volatile uint32_t *)p);
        if (!sent) return; /* Resume at this line next task wake; no full reprint. */
        ++fault_snapshot_print_index;
        label=end+1;
    }
    if (fault_snapshot_print_index==n+1U && UART_SendReliableFormatted(line,sizeof(line),
        "END CPU_HZ=%lu\r\n",(unsigned long)SystemCoreClock))
        ++fault_snapshot_print_index;
}
