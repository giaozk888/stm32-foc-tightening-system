/* Diagnostic A only. No START, persistent writes or power enable. */
static uint8_t DobGainAb_Command(const char *cmd,char *out,size_t size)
{
    const char *prefix="MOTOR TEST MECH DOB FB GAIN ";
    if(strncmp(cmd,prefix,strlen(prefix)))return 0;
    const char *arg=cmd+strlen(prefix);
    float gain;
    if(!strcmp(arg,"250000"))gain=.25f;
    else if(!strcmp(arg,"500000"))gain=.5f;
    else {snprintf(out,size,"ERR DOBGAIN VALUE");return 1;}
    taskENTER_CRITICAL();
    if(Tightening_IsBusy()||tightening_start_request||tightening_stop_request||
       motor_control_mode!=MOTOR_MODE_IDLE||(DRIVER_SD_GPIO_Port->ODR&DRIVER_SD_Pin)||
       (TIM1->BDTR&(TIM_BDTR_MOE|TIM_BDTR_AOE))||TIM1->CCER||adc_fault||foc_fault){
        taskEXIT_CRITICAL();snprintf(out,size,"ERR DOBGAIN BUSY_OR_OUTPUT_ENABLED");return 1;
    }
    dob_feedback=(DobFeedbackCandidate){0}; /* Must explicitly enable after selection. */
    dob_gain_ab=gain;
    taskEXIT_CRITICAL();
    snprintf(out,size,"OK DOBGAIN GAIN_PPM=%lu ON=0 RAM_ONLY=1",(unsigned long)(gain*1e6f+.5f));
    return 1;
}
