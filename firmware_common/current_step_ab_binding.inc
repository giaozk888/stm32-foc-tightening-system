/* Exclusive diagnostic reference owner. Existing admission, PI arithmetic,
 * pending stage/entry commit, and independent safety guards are reused. */
static uint8_t TighteningIntent_PrecheckOnly(void)
{return (uint8_t)(current_step_ab.admitting&&motor_control_mode==MOTOR_MODE_IDLE);}
static void TighteningIntent_PrintStatus(uint32_t id)
{
    char out[128];Protocol_SendFormatted(out,sizeof out,
        "%lu OK CURRENT_STEP STATE=%u STEP=%u DONE=%u REASON=%u\r\n",(unsigned long)id,
        current_step_ab.state,current_step_ab.step,current_step_ab.completed,current_step_ab.reason);
}
__attribute__((noinline,optimize("Os")))
static uint8_t CurrentStep_FocReference(void)
{
    foc_id_ref_A=0.0f;foc_iq_ref_A=0.0f;
    if(current_step_ab.state!=CS_ACTIVE)return 1U;
    if(cl_session.state!=CL_RUNNING||adc_fault||foc_fault){
        CurrentStep_End(&current_step_ab,CS_ABORT,CS_PROTECTION);ProtectedLoop_Stop();return 0U;
    }
    int selected=(int)current_step_pi_new;float iq=0;
    if(!CurrentStep_Reference(&current_step_ab,cl_frame.source_us,&selected,&iq)){
        ProtectedLoop_Stop();return 0U;
    }
    if(current_step_ab.reset_pi){
        FocCurrentPi_Reset(&foc_int_d_V,&foc_int_q_V);
        ProtectedLoop_PwmInvalidate(); /* existing safe handoff, no CCR writes */
    }
    current_step_pi_new=(unsigned)selected;
    foc_iq_ref_A=iq;return 1U;
}
__attribute__((noinline,optimize("Os")))
static void CurrentStep_Capture(void)
{
    CurrentStep_Record(&current_step_ab,cl_frame.source_us,cl_seq,
        foc_iq_ref_A,foc_iq_A,foc_id_A,foc_vq_V,foc_vd_V,foc_int_q_V,foc_int_d_V,
        current_step_out_q,current_step_out_d,encoder_omega_e_rad_s,current_step_saturated,(uint16_t)cl_flags);
}
__attribute__((optimize("Os")))
static uint8_t CurrentStep_Command(const char *cmd,char *out,size_t size)
{
    if(!strcmp(cmd,"MOTOR TEST PROFILE")){
        snprintf(out,size,"OK MOTOR TEST PROFILE NAME=CURRENT_STEP_AB FSM=BYPASSED SPEED_PI=0 ID_REF=0 LIMIT_MA=500 MANUAL_BATCH=1");return 1U;
    }
    const char *prefix="MOTOR TEST CURRENT STEP ";size_t n=strlen(prefix);
    if(strncmp(cmd,prefix,n))return 0U;
    const char *suffix=cmd+n;
#if defined(FOC_CURRENT_STEP_IDENT_POLICY)
#if !defined(AS5047P_DMA_TERMINAL_FIX) || !defined(AS5047P_DMA_TIMING_POLICY_V2) || AS_DMA_TRANSACTION_US != 400U
#error Step identification-policy adapter requires the complete existing encoder policy
#endif
    if(!strcmp(suffix,"ENCODER TIME")){
        uint32_t slow_count,ok_max_us;
        AS5047P_DmaGetTimingStats(&slow_count,&ok_max_us);
        snprintf(out,size,"OK ENC POLICY=2 TERMINAL_FIX=1 WARN_US=%u DEADLINE_US=%u SCHED_US=%u PERIOD_US=%u AGE_US=%u CONTROL_US=%u SLOW_N=%lu OK_MAX_US=%lu",
            (unsigned)AS_DMA_TRANSACTION_WARN_US,(unsigned)AS_DMA_TRANSACTION_US,
            (unsigned)AS_DMA_SCHEDULE_LATE_US,(unsigned)AS_DMA_PERIOD_US,
            (unsigned)AS_DMA_SAMPLE_MAX_AGE_US,(unsigned)AS_DMA_CONTROL_WATCHDOG_US,
            (unsigned long)slow_count,(unsigned long)ok_max_us);return 1U;
    }
#endif
    if(!strcmp(suffix,"AB CONFIRM")){
        taskENTER_CRITICAL();
        uint8_t ready=(uint8_t)(cl_session.state==CL_READY&&!cl_session.used&&ProtectedLoop_Ready()&&
            motor_control_mode==MOTOR_MODE_IDLE&&!Tightening_IsBusy()&&!tightening_start_request&&
            !tightening_stop_request&&encoder_valid&&fabsf(encoder_speed_rpm)<=2.0f&&
            !(DRIVER_SD_GPIO_Port->ODR&DRIVER_SD_Pin)&&!(TIM1->BDTR&(TIM_BDTR_MOE|TIM_BDTR_AOE))&&!TIM1->CCER);
        int ok=CurrentStep_Queue(&current_step_ab,ready,(unsigned)(FOC_RUNDOWN240_IQ_LIMIT_A*1000.0f+.5f));
        taskEXIT_CRITICAL();
        snprintf(out,size,ok?"OK CURRENT_STEP QUEUED ONE_BATCH=1 STEPS=10 LOCKED_ACK=1":"ERR CURRENT_STEP NOT_READY");return 1U;
    }
    if(!strcmp(suffix,"STATUS")){
        snprintf(out,size,"OK CURRENT_STEP STATE=%u REASON=%u STEP=%u DONE=%u USED=%u POS_PASS=%u ROWS=60 PRE_US=20000 ON_US=30000 POST_US=30000 MAX_US=800000",
            current_step_ab.state,current_step_ab.reason,current_step_ab.step,current_step_ab.completed,
            current_step_ab.used,current_step_ab.positive_pass);return 1U;
    }
    if(current_step_ab.state<CS_DONE||cl_session.state==CL_RUNNING){snprintf(out,size,"ERR CURRENT_STEP ACTIVE_OR_EMPTY");return 1U;}
    if(!strncmp(suffix,"METRIC ",7U)){
        char *end=NULL;unsigned long k=strtoul(suffix+7U,&end,10);
        if(!end||*end||end==suffix+7U||k>=CS_STEPS){snprintf(out,size,"ERR CURRENT_STEP INDEX");return 1U;}
        const CurrentStepMetric *m=&current_step_ab.metrics[k];
        snprintf(out,size,"OK CSM K=%lu BS=%ld B=%ld TS=%ld PK=%ld BN=%lu TN=%lu N=%lu T10=%lu T90=%lu SET=%lu GAP=%lu CROSS=%lu MASK=%lu CLIP=%u",
            k,(long)m->baseline_sum,(long)m->baseline,(long)m->tail_sum,(long)m->peak,
            (unsigned long)m->baseline_n,(unsigned long)m->tail_n,(unsigned long)m->high_n,
            (unsigned long)m->t10_us,(unsigned long)m->t90_us,(unsigned long)m->settle_us,
            (unsigned long)m->gaps,(unsigned long)m->crossings,(unsigned long)m->valid_mask,m->clipped);return 1U;
    }
    if(!strncmp(suffix,"ROW ",4U)){
        char *end=NULL;unsigned long k=strtoul(suffix+4U,&end,10);
        if(!end||*end||end==suffix+4U||k>=CS_STEPS*CS_EVENTS){snprintf(out,size,"ERR CURRENT_STEP INDEX");return 1U;}
        const CurrentStepFrame *r=&current_step_ab.rows[k/CS_EVENTS][k%CS_EVENTS];
        snprintf(out,size,"OK CS K=%lu US=%lu SEQ=%lu QR=%d Q=%d D=%d VQ=%d VD=%d IQ=%d ID=%d OQ=%d OD=%d WE=%d FLAGS=%u FAULT=%u",
            k,(unsigned long)r->us,(unsigned long)r->seq,r->iq_ref,r->iq,r->id,r->vq,r->vd,
            r->int_q,r->int_d,r->out_q,r->out_d,r->omega,r->flags,r->fault);return 1U;
    }
    snprintf(out,size,"ERR CURRENT_STEP COMMAND");return 1U;
}
__attribute__((optimize("Os")))
static void TighteningTask(void *argument)
{
    /* Exclusive diagnostic does not use these normal FSM callbacks. Keep
     * compile-time references (no calls/code) rather than suppress warnings. */
    (void)LatestOriginal_FsmService;(void)MotorControl_SetSpeed;
    (void)TighteningResult_Sample;(void)TighteningResult_PrintSummary;
    (void)TighteningRepeat_ResetCurrentCycle;(void)TighteningRepeat_StoreCurrentCycle;
    (void)TighteningSession_Begin;(void)Protocol_SendDeferredStartError;(void)Protocol_SendCycleEvent;
    (void)argument;TickType_t wake=xTaskGetTickCount();MotorControl_SetIdle();
    UART_SendLiteral("CURRENT_STEP_AB_DIAGNOSTIC: LOCK ROTOR; manual one batch; no START\r\n");
    for(;;){
        if(tightening_start_request||tightening_stop_request){
            uint32_t request=tightening_start_request_id;uint8_t start=tightening_start_request;
            tightening_start_request=tightening_stop_request=0U;
            if(current_step_ab.state==CS_ACTIVE||current_step_ab.state==CS_QUEUED){
                CurrentStep_End(&current_step_ab,CS_ABORT,CS_CANCELLED);ProtectedLoop_Stop();
            }
            if(start)Protocol_SendError(request,PROTO_ERR_BUSY,"USE_CURRENT_STEP_AB_CONFIRM");
        }
        if(current_step_ab.state==CS_ACTIVE&&cl_session.state!=CL_RUNNING){
            CurrentStep_End(&current_step_ab,CS_ABORT,CS_PROTECTION);MotorControl_SetIdle();
        }
        if(current_step_ab.state==CS_ACTIVE&&
           (uint32_t)(AS5047P_DmaNowUs()-current_step_ab.start_us)>CS_MAX_US+1000U){
            CurrentStep_End(&current_step_ab,CS_ABORT,CS_TIME);ProtectedLoop_Stop();
        }
        if(current_step_ab.state==CS_QUEUED){
            if(adc_fault||foc_fault||!cl_armed||cl_session.state!=CL_READY){
                CurrentStep_End(&current_step_ab,CS_ABORT,CS_PROTECTION);ProtectedLoop_Stop();continue;
            }
            if(!current_step_ab.prepared){current_step_ab.encoder_before=cl_outer_n;current_step_ab.prepared=1U;}
            else if(cl_outer_n!=current_step_ab.encoder_before){
                current_step_ab.admitting=1U;uint8_t ok=LatestOriginal_Admit();current_step_ab.admitting=0U;
                if(!ok){CurrentStep_End(&current_step_ab,CS_ABORT,CS_NOT_READY);ProtectedLoop_Stop();}
            }
        }
        if(current_step_ab.state>=CS_DONE)MotorControl_SetIdle();
        vTaskDelayUntil(&wake,pdMS_TO_TICKS(1U));
    }
}
