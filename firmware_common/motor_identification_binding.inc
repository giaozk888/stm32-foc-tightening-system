/* Exclusive diagnostic owner. No PWM register/gate writes, no new PI math. */
#if defined(FOC_IDENT_TIMING_TRACE_ENABLE)
static void MotorIdent_TimingContext(void)
{
    MotorIdentTimingFailure *t=&motor_ident.timing_failure;
    if (!t->valid || t->context_valid) return;
    t->adc_seq=injected_seq_count;t->frame_seq=cl_frame.source_seq;t->pair_us=cl_last_us;
    t->hold_before=motor_ident.last_hold_count;t->hold_now=current_hold_total;
    t->path=cl_current_path;
    __DMB();t->context_valid=1U;
}
#endif
static uint8_t TighteningIntent_PrecheckOnly(void)
{ return (uint8_t)(motor_ident.admitting && motor_control_mode==MOTOR_MODE_IDLE); }
static void TighteningIntent_PrintStatus(uint32_t request_id)
{
    char out[128];Protocol_SendFormatted(out,sizeof out,
        "%lu OK IDENT MODE=%u STATUS=%u REASON=%u N=%lu\r\n",
        (unsigned long)request_id,motor_ident.mode,motor_ident.status,motor_ident.reason,
        (unsigned long)motor_ident.count);
}
__attribute__((noinline,optimize("Os")))
static uint8_t MotorIdent_Ref(float id,float iq)
{
    if (motor_ident.status!=MID_ACTIVE) return 1;
    motor_ident.pending_before=cl_pwm_pending.source_seq;
    float d=0,q=0;
    if (cl_session.state!=CL_RUNNING || adc_fault || foc_fault) {
        MotorIdent_End(&motor_ident,MID_PROTECTION);ProtectedLoop_Stop();return 0;
    }
#if defined(FOC_IDENT_RS_GAP_ADMISSION_ENABLE)
    motor_ident.rs_hold_delta=current_hold_total-motor_ident.last_hold_count;
#endif
    uint8_t ok=MotorIdent_Reference(&motor_ident,cl_frame.source_us,cl_seq,
        encoder_position_deg,encoder_speed_rpm,id,iq,&d,&q);
#if defined(FOC_IDENT_TIMING_TRACE_ENABLE)
    /* Capture before STOP can change owner state. No per-frame UART/math. */
    if (!ok) MotorIdent_TimingContext();
    if (ok) motor_ident.last_hold_count=current_hold_total;
#endif
#if defined(FOC_IDENT_CURRENT_REJECT_ENABLE)
    if (motor_ident.sample_rejected && !motor_ident.first_reject_valid) {
        /* Before STOP/shadow FOC overwrites context. Voltages are PREVIOUS
         * calculated commands, not phase-voltage measurements. */
        motor_ident.first_reject=(MotorIdentFrame){.us=cl_frame.source_us-motor_ident.start_us,
            .seq=cl_seq,.pending_before=motor_ident.pending_before,
#if defined(FOC_IDENT_VOLTAGE_STEP_DIAG)
            .raw_u=cl_frame.u,.raw_v=cl_frame.v,
#else
            .id_ref=foc_id_ref_A,.iq_ref=foc_iq_ref_A,
#endif
            .id=id,.iq=iq,
            .vd=foc_vd_V,.vq=foc_vq_V,.angle=encoder_theta_e,.speed=encoder_speed_rpm,
            .mode=motor_ident.mode,.status=motor_ident.status,.reason=MID_CURRENT};
        motor_ident.first_raw_u=cl_frame.u;motor_ident.first_raw_v=cl_frame.v;
        __DMB();motor_ident.first_reject_valid=1U;
    }
#endif
    foc_id_ref_A=d;foc_iq_ref_A=q;
    if (!ok) ProtectedLoop_Stop();
    return ok;
}
__attribute__((noinline,optimize("Os")))
static void MotorIdent_Capture(void)
{
    if (motor_ident.status!=MID_ACTIVE) return;
    MotorIdentFrame row={.us=cl_frame.source_us,.seq=cl_seq,
        .pending_before=motor_ident.pending_before,
#if defined(FOC_IDENT_VOLTAGE_STEP_DIAG)
        /* Tail point only, NOT the physical aperture/commit point. */
        .raw_u=cl_frame.u,.raw_v=cl_frame.v,.tail_cnt=(uint16_t)TIM1->CNT,
        .tail_flags=(uint16_t)((TIM1->CR1&TIM_CR1_DIR)!=0U),
#else
        .id_ref=foc_id_ref_A,.iq_ref=foc_iq_ref_A,
#endif
        .id=foc_id_A,.iq=foc_iq_A,
        .vd=foc_vd_V,.vq=foc_vq_V,.angle=encoder_theta_e,.speed=encoder_speed_rpm};
    if (!MotorIdent_Record(&motor_ident,row)) ProtectedLoop_Stop();
}
__attribute__((optimize("Os")))
static uint8_t MotorIdent_Command(const char *cmd,char *out,size_t size)
{
    if (strncmp(cmd,"MOTOR TEST IDENT ",17U)) return 0;
    uint8_t mode=0;float amps=0;
    if (MotorIdent_Parse(cmd,&mode,&amps)) {
        taskENTER_CRITICAL();
        uint8_t ready=(uint8_t)(!motor_ident.used && cl_session.state==CL_READY &&
            !cl_session.used && ProtectedLoop_Ready() && motor_control_mode==MOTOR_MODE_IDLE &&
            !Tightening_IsBusy() && !tightening_start_request && !tightening_stop_request &&
            encoder_valid && fabsf(encoder_speed_rpm)<=MID_SPEED_MAX_RPM &&
            !(DRIVER_SD_GPIO_Port->ODR & DRIVER_SD_Pin) &&
            !(TIM1->BDTR & (TIM_BDTR_MOE|TIM_BDTR_AOE)) && !TIM1->CCER);
        if (ready) {
            /* Zero BSS already initialized; no large memset under IRQ mask. */
            motor_ident.mode=mode;motor_ident.current_a=amps;
            motor_ident.used=motor_ident.confirmed_locked=1U;motor_ident.status=MID_QUEUED;
        }
        taskEXIT_CRITICAL();
        snprintf(out,size,ready ? "OK IDENT QUEUED ONE_SHOT=1 LOCKED_ACK=1" : "ERR IDENT NOT_READY");
        return 1;
    }
    /* Trace immutable only after gate-off completion; no live bulk UART. */
    if (!strcmp(cmd,"MOTOR TEST IDENT STATUS")) {
        snprintf(out,size,"OK IDENT MODE=%u STATUS=%u REASON=%u N=%lu USED=%u IMAX_MA=200 VMAX_MV=200",
            motor_ident.mode,motor_ident.status,motor_ident.reason,
            (unsigned long)motor_ident.count,motor_ident.used);return 1;
    }
#if defined(AS5047P_DMA_TIMING_POLICY_V2)
#if defined(FOC_IDENT_VOLTAGE_STEP_DIAG)
    if (!strcmp(cmd,"MOTOR TEST IDENT VOLTAGE POLICY")) {
        snprintf(out,size,"OK MID VOLTAGE_STEP=1 PI_BYPASS=1 STEP_MV=50 STEP_US=100000 END_US=104000 RAW_FRAME_ABI=1");
        return 1;
    }
#endif
    if (!strcmp(cmd,"MOTOR TEST IDENT ENCODER TIME")) {
        uint32_t slow_count,ok_max_us;
        AS5047P_DmaGetTimingStats(&slow_count,&ok_max_us);
        snprintf(out,size,"OK ENC POLICY=2 WARN_US=%u DEADLINE_US=%u SCHED_US=%u PERIOD_US=%u AGE_US=%u CONTROL_US=%u SLOW_N=%lu OK_MAX_US=%lu",
            (unsigned)AS_DMA_TRANSACTION_WARN_US,(unsigned)AS_DMA_TRANSACTION_US,
            (unsigned)AS_DMA_SCHEDULE_LATE_US,(unsigned)AS_DMA_PERIOD_US,
            (unsigned)AS_DMA_SAMPLE_MAX_AGE_US,(unsigned)AS_DMA_CONTROL_WATCHDOG_US,
            (unsigned long)slow_count,(unsigned long)ok_max_us);return 1;
    }
#endif
#if MID_RS_SOFT_DT_MAX_US != 55U
    if (!strcmp(cmd,"MOTOR TEST IDENT TIME POLICY")) {
        snprintf(out,size,"OK MID RS_DT_MAX=%u L_DT_MAX=%u DT_MIN=45 GAP_DT_PER_SEQ_MAX=55"
#if defined(FOC_IDENT_L_RS_ADMISSION_ENABLE)
            " L_RS_ADMISSION=1"
#endif
            ,(unsigned)MID_RS_SOFT_DT_MAX_US,(unsigned)MID_L_SOFT_DT_MAX_US);return 1;
    }
#endif
#if defined(FOC_IDENT_TIMING_TRACE_ENABLE)
    if (!strcmp(cmd,"MOTOR TEST IDENT TIMING") || !strcmp(cmd,"MOTOR TEST IDENT TIMING CONTEXT")) {
        if (motor_ident.status<MID_DONE || cl_session.state==CL_RUNNING) {
            snprintf(out,size,"ERR IDENT ACTIVE");return 1;
        }
        const MotorIdentTimingFailure *t=&motor_ident.timing_failure;
        if (!strcmp(cmd,"MOTOR TEST IDENT TIMING"))
            snprintf(out,size,"OK MID TV=%lu PS=%lu PU=%lu S=%lu U=%lu DS=%lu DT=%lu WHY=%lu",
                (unsigned long)t->valid,(unsigned long)t->prev_seq,(unsigned long)t->prev_us,
                (unsigned long)t->seq,(unsigned long)t->us,(unsigned long)t->delta_seq,
                (unsigned long)t->delta_us,(unsigned long)t->flags);
        else
            snprintf(out,size,"OK MID CV=%lu ADC=%lu FRAME=%lu PAIR_US=%lu HB=%lu HN=%lu PATH=%lu",
                (unsigned long)t->context_valid,(unsigned long)t->adc_seq,(unsigned long)t->frame_seq,
                (unsigned long)t->pair_us,(unsigned long)t->hold_before,(unsigned long)t->hold_now,
                (unsigned long)t->path);
        return 1;
    }
#endif
#if defined(FOC_IDENT_RS_GAP_ADMISSION_ENABLE)
    if (!strcmp(cmd,"MOTOR TEST IDENT RS GAPS")) {
        if (motor_ident.status<MID_DONE || cl_session.state==CL_RUNNING) {
            snprintf(out,size,"ERR IDENT ACTIVE");return 1;
        }
#if defined(FOC_IDENT_RS_GAP_COUNT_ONLY)
        unsigned total_stop=(unsigned)!MotorIdent_RsAdmission(&motor_ident);
        snprintf(out,size,"OK MID RS_GAPS=%lu SKIPPED=%lu MAX_GAP=%lu BUDGET=%u RUN_LIMIT=2 TOTAL_STOP=%u",
            (unsigned long)motor_ident.rs_gap_events,(unsigned long)motor_ident.rs_skipped_pairs,
            (unsigned long)motor_ident.rs_max_skipped,total_stop ? MID_RS_MAX_SKIPPED_PAIRS : 0U,total_stop);
#else
        snprintf(out,size,"OK MID RS_GAPS=%lu SKIPPED=%lu MAX_GAP=%lu BUDGET=16 RUN_LIMIT=2",
            (unsigned long)motor_ident.rs_gap_events,(unsigned long)motor_ident.rs_skipped_pairs,
            (unsigned long)motor_ident.rs_max_skipped);
#endif
        return 1;
    }
#endif
#if defined(FOC_IDENT_CURRENT_REJECT_ENABLE)
    if (!strcmp(cmd,"MOTOR TEST IDENT REJECT")) {
        if (motor_ident.status<MID_DONE || cl_session.state==CL_RUNNING) {
            snprintf(out,size,"ERR IDENT ACTIVE");return 1;
        }
#if defined(FOC_IDENT_RS_REJECT_COUNT_ONLY)
        unsigned stop=(unsigned)!MotorIdent_RsAdmission(&motor_ident);
        snprintf(out,size,"OK MID REJECT=%lu GOOD=%lu RUN=%u MAX_RUN=%u REJECT_MAX=%u RUN_LIMIT=%u FIRST=%u TOTAL_STOP=%u RUN_STOP=%u RUN_SAT=255",
            (unsigned long)motor_ident.current_reject_count,(unsigned long)motor_ident.current_good_count,
            motor_ident.current_reject_run,motor_ident.max_current_reject_run,
            stop ? 16U : 0U,stop ? 3U : 0U,motor_ident.first_reject_valid,stop,stop);
#elif defined(FOC_IDENT_RS_NO_TOTAL_REJECT_EXIT)
        unsigned total_stop=(unsigned)(motor_ident.mode!=MID_RS);
        snprintf(out,size,"OK MID REJECT=%lu GOOD=%lu RUN=%u MAX_RUN=%u REJECT_MAX=%u RUN_LIMIT=3 FIRST=%u TOTAL_STOP=%u",
            (unsigned long)motor_ident.current_reject_count,(unsigned long)motor_ident.current_good_count,
            motor_ident.current_reject_run,motor_ident.max_current_reject_run,
            total_stop ? 16U : 0U,motor_ident.first_reject_valid,total_stop);
#else
        snprintf(out,size,"OK MID REJECT=%lu GOOD=%lu RUN=%u MAX_RUN=%u REJECT_MAX=16 RUN_LIMIT=3 FIRST=%u",
            (unsigned long)motor_ident.current_reject_count,(unsigned long)motor_ident.current_good_count,
            motor_ident.current_reject_run,motor_ident.max_current_reject_run,motor_ident.first_reject_valid);
#endif
        return 1;
    }
    if (!strcmp(cmd,"MOTOR TEST IDENT REJECT ROW")) {
        if (motor_ident.status<MID_DONE || cl_session.state==CL_RUNNING || !motor_ident.first_reject_valid) {
            snprintf(out,size,"ERR IDENT NO_FROZEN_REJECT");return 1;
        }
        const MotorIdentFrame *f=&motor_ident.first_reject;
        snprintf(out,size,"OK MID FIRST_US=%lu SEQ=%lu RAW_U=%u RAW_V=%u D_UA=%ld Q_UA=%ld DR_UA=%ld QR_UA=%ld PREV_VD_UV=%ld PREV_VQ_UV=%ld",
            (unsigned long)f->us,(unsigned long)f->seq,motor_ident.first_raw_u,motor_ident.first_raw_v,
            (long)(f->id*1e6f),(long)(f->iq*1e6f),
#if defined(FOC_IDENT_VOLTAGE_STEP_DIAG)
            0L,0L,
#else
            (long)(f->id_ref*1e6f),(long)(f->iq_ref*1e6f),
#endif
            (long)(f->vd*1e6f),(long)(f->vq*1e6f));return 1;
    }
#endif
    unsigned index;int used=0;
    if (sscanf(cmd,"MOTOR TEST IDENT ROW %u%n",&index,&used)==1 && cmd[used]=='\0' &&
        motor_ident.status>=MID_DONE && cl_session.state!=CL_RUNNING && index<motor_ident.count) {
        const MotorIdentFrame *f=&motor_ident.rows[index];
        /* Scaled foreground-only integers. Exact binary struct retained in RAM. */
#if defined(FOC_IDENT_VOLTAGE_STEP_DIAG)
        snprintf(out,size,"OK MID K=%u US=%lu SEQ=%lu PSEQ=%lu M=%u S=%u F=%u RU=%u RV=%u TCNT=%u TDIR=%u D=%ld Q=%ld VD=%ld VQ=%ld A=%ld RPM=%ld",
            index,(unsigned long)f->us,(unsigned long)f->seq,(unsigned long)f->pending_before,
            f->mode,f->status,f->reason,f->raw_u,f->raw_v,f->tail_cnt,f->tail_flags,
            (long)(f->id*1e6f),(long)(f->iq*1e6f),(long)(f->vd*1e6f),(long)(f->vq*1e6f),
            (long)(f->angle*1e6f),(long)(f->speed*1000));return 1;
#else
        snprintf(out,size,"OK MID K=%u US=%lu SEQ=%lu PSEQ=%lu M=%u S=%u F=%u DR=%ld QR=%ld D=%ld Q=%ld VD=%ld VQ=%ld A=%ld RPM=%ld",
            index,(unsigned long)f->us,(unsigned long)f->seq,(unsigned long)f->pending_before,
            f->mode,f->status,f->reason,(long)(f->id_ref*1e6f),(long)(f->iq_ref*1e6f),
            (long)(f->id*1e6f),(long)(f->iq*1e6f),(long)(f->vd*1e6f),(long)(f->vq*1e6f),
            (long)(f->angle*1e6f),(long)(f->speed*1000));return 1;
#endif
    }
    if (!strcmp(cmd,"MOTOR TEST IDENT GEOMETRY")) {
        snprintf(out,size,"OK MID ARR=%lu CCR4=%lu CR1=%lu RCR=%lu JSQR=%lu"
#if defined(FOC_IDENT_VOLTAGE_STEP_DIAG)
            " VOLTAGE_STEP=1 PI_BYPASS=1"
#else
            " CURRENT_STEP=1"
#endif
            " CANDIDATE_ONLY=1"
#if !MID_TRAVEL_EXIT_ENABLE
            " TRAVEL_EXIT=OFF"
#endif
            ,
            (unsigned long)motor_ident.arr,(unsigned long)motor_ident.ccr4,
            (unsigned long)motor_ident.cr1,(unsigned long)motor_ident.rcr,
            (unsigned long)motor_ident.jsqr);return 1;
    }
    snprintf(out,size,"ERR IDENT COMMAND_OR_ACTIVE");return 1;
}
__attribute__((optimize("Os")))
static void TighteningTask(void *argument)
{
    (void)argument;TickType_t wake=xTaskGetTickCount();MotorControl_SetIdle();
    UART_SendLiteral("MOTOR_IDENT_DIAGNOSTIC: LOCK ROTOR; manual one-shot; no START\r\n");
    for (;;) {
        if (tightening_start_request || tightening_stop_request) {
            uint32_t req=tightening_start_request_id;uint8_t start=tightening_start_request;
            tightening_start_request=tightening_stop_request=0;
            if (motor_ident.status==MID_ACTIVE || motor_ident.status==MID_QUEUED) {
                ProtectedLoop_Stop();MotorIdent_End(&motor_ident,MID_CANCELLED);
            }
            if (start) Protocol_SendError(req,PROTO_ERR_BUSY,"IDENT_USE_EXPLICIT_LOCKED_COMMAND");
        }
        if (motor_ident.status==MID_ACTIVE && cl_session.state!=CL_RUNNING) {
            MotorIdent_End(&motor_ident,MID_PROTECTION);MotorControl_SetIdle();
        }
        if (motor_ident.status==MID_ACTIVE &&
            (uint32_t)(AS5047P_DmaNowUs()-motor_ident.start_us)>
            (motor_ident.mode==MID_RS ? MID_RS_DURATION_US : MID_L_DURATION_US)+1000U) {
            /* Independent task duration cap if no normal ADC frame reaches
             * the reference owner. Original TIM7/lease still runs as well. */
            ProtectedLoop_Stop();MotorIdent_End(&motor_ident,MID_TIMING);
        }
        if (motor_ident.status==MID_QUEUED) {
            if (!motor_ident.prepared) {
                motor_ident.encoder_before=cl_outer_n;motor_ident.prepared=1U;
            } else if (cl_outer_n!=motor_ident.encoder_before) {
                motor_ident.admitting=1U;
                uint8_t ok=LatestOriginal_Admit();motor_ident.admitting=0U;
                if (!ok) {ProtectedLoop_Stop();MotorIdent_End(&motor_ident,MID_NOT_READY);}
            }
        }
        if (motor_ident.status>=MID_DONE) MotorControl_SetIdle();
        vTaskDelayUntil(&wake,pdMS_TO_TICKS(1U));
    }
}
