/* Candidate A only; selection before the single-use session, never starts it. */
static uint8_t DobWarmupAb_Command(const char *cmd,char *out,size_t size)
{
    const char *prefix="MOTOR TEST MECH DOB WARM ";
    if(strncmp(cmd,prefix,strlen(prefix)))return 0;
    const char *arg=cmd+strlen(prefix);
    if(strcmp(arg,"CFG")){
        uint32_t tau;
        if(!strcmp(arg,"SET 3"))tau=3U;
        else if(!strcmp(arg,"SET 5"))tau=5U;
        else {snprintf(out,size,"ERR DOBWARM VALUE");return 1;}
        taskENTER_CRITICAL();
        if(Tightening_IsBusy()||tightening_start_request||tightening_stop_request||
           motor_control_mode!=MOTOR_MODE_IDLE||cl_session.state!=CL_READY||cl_session.used||
           mechanical_dob_monitor.running||dob_feedback.enabled||adc_fault||foc_fault||
           (DRIVER_SD_GPIO_Port->ODR&DRIVER_SD_Pin)||
           (TIM1->BDTR&(TIM_BDTR_MOE|TIM_BDTR_AOE))||TIM1->CCER){
            taskEXIT_CRITICAL();snprintf(out,size,"ERR DOBWARM BUSY_OR_OUTPUT_ENABLED");return 1;
        }
        dob_warmup_tau=tau;
        taskEXIT_CRITICAL();
    }
    snprintf(out,size,"OK DOBWARM TAU=%lu BW_MHZ=2000 DEFAULT_TAU=%lu RAM_ONLY=1",
        (unsigned long)dob_warmup_tau,(unsigned long)DOB_WARMUP_DEFAULT_TAU);
    return 1;
}
