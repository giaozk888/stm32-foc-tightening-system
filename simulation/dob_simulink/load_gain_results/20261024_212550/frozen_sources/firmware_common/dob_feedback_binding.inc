/* Separate task command adapter, not part of the read-only observer.
 * Used by diagnostic and selected normal A profiles. Never starts a motor;
 * only changes mode with all outputs OFF. */
#if defined(FOC_DOB_GAIN_AB_DIAG)
#include "dob_gain_ab_binding.inc"
#endif
static uint8_t DobFeedback_Command(const char *cmd,char *out,size_t size)
{
#if defined(FOC_DOB_GAIN_AB_DIAG)
    if(DobGainAb_Command(cmd,out,size))return 1;
#endif
    if(strncmp(cmd,"MOTOR TEST MECH DOB FB ",sizeof("MOTOR TEST MECH DOB FB ")-1U))return 0;
    const char *arg=cmd+sizeof("MOTOR TEST MECH DOB FB ")-1U;
    if(!strcmp(arg,"ON")||!strcmp(arg,"OFF")){
        taskENTER_CRITICAL();
        if(Tightening_IsBusy()||tightening_start_request||tightening_stop_request||
           motor_control_mode!=MOTOR_MODE_IDLE||(DRIVER_SD_GPIO_Port->ODR&DRIVER_SD_Pin)||
           (TIM1->BDTR&(TIM_BDTR_MOE|TIM_BDTR_AOE))||TIM1->CCER){
            taskEXIT_CRITICAL();snprintf(out,size,"ERR DOBFB BUSY_OR_OUTPUT_ENABLED");return 1;
        }
        dob_feedback=(DobFeedbackCandidate){.enabled=(uint32_t)!strcmp(arg,"ON")};
        taskEXIT_CRITICAL();
    }
    DobFeedbackCandidate f;
    taskENTER_CRITICAL();f=dob_feedback;taskEXIT_CRITICAL();
    if(!strcmp(arg,"ON")||!strcmp(arg,"OFF")||!strcmp(arg,"CFG"))
        snprintf(out,size,"OK DOBFB ON=%lu GAIN_PPM=%lu CAP_UA=25000 FRAC_PPM=50000 SLEW_UA_S=250000 FRESH_US=2000 HOLD_US=5000 ZERO_US=20000",
            (unsigned long)f.enabled,(unsigned long)(DOB_FB_GAIN*1000000.f+.5f));
    else if(!strcmp(arg,"STATUS"))
        snprintf(out,size,"OK DOBFB ON=%lu US=%lu STATE=%lu AGE_US=%lu COMP_UA=%ld D_UA=%ld",
            (unsigned long)f.enabled,(unsigned long)f.sample_us,(unsigned long)f.state,(unsigned long)f.age_us,
            (long)MechanicalDob_Fixed(f.iq_comp_a,1e6f),(long)MechanicalDob_Fixed(f.disturbance_a,1e6f));
    else if(!strcmp(arg,"SUM"))
        snprintf(out,size,"OK DOBFB ON=%lu US=%lu PI_UA=%ld RAW_UA=%ld REF_UA=%ld I_UA=%ld SAT=%lu",
            (unsigned long)f.enabled,(unsigned long)f.sample_us,
            (long)MechanicalDob_Fixed(f.iq_pi_a,1e6f),(long)MechanicalDob_Fixed(f.iq_raw_a,1e6f),
            (long)MechanicalDob_Fixed(f.iq_ref_a,1e6f),(long)MechanicalDob_Fixed(f.integral_a,1e6f),(unsigned long)f.saturation);
    else if(!strcmp(arg,"STATS"))
        snprintf(out,size,"OK DOBFB ON=%lu N=%lu GOOD=%lu HOLD=%lu FADE=%lu CLEAR=%lu CLAMP=%lu PEAK_UA=%ld",
            (unsigned long)f.enabled,(unsigned long)f.updates,(unsigned long)f.valid_updates,
            (unsigned long)f.holds,(unsigned long)f.fades,(unsigned long)f.clears,(unsigned long)f.clamps,
            (long)MechanicalDob_Fixed(f.peak_a,1e6f));
    else snprintf(out,size,"ERR DOBFB COMMAND");
    return 1;
}
