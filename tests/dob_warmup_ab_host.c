#include "mechanical_dob_monitor.h"
#include "dob_normal_control.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>
static MechanicalDobMonitor mechanical_dob_monitor;
static DobFeedbackCandidate dob_feedback;
static struct {uint32_t ODR;} port;
static struct {uint32_t BDTR,CCER;} tim;
static struct {uint32_t state,used;} cl_session;
static uint32_t busy,tightening_start_request,tightening_stop_request,motor_control_mode,adc_fault,foc_fault;
#define DRIVER_SD_GPIO_Port (&port)
#define DRIVER_SD_Pin 1U
#define TIM1 (&tim)
#define TIM_BDTR_MOE 0x8000U
#define TIM_BDTR_AOE 0x4000U
#define MOTOR_MODE_IDLE 0U
#define CL_READY 1U
#define taskENTER_CRITICAL() ((void)0)
#define taskEXIT_CRITICAL() ((void)0)
static uint32_t Tightening_IsBusy(void){return busy;}
#include "dob_warmup_ab_binding.inc"
static void command_guard(void){
    char out[160];cl_session.state=CL_READY;
    assert(DobWarmupAb_Command("MOTOR TEST MECH DOB WARM SET 3",out,sizeof out)&&dob_warmup_tau==3);
    uint32_t *guards[]={&busy,&tightening_start_request,&tightening_stop_request,&motor_control_mode,
        &cl_session.used,&mechanical_dob_monitor.running,&dob_feedback.enabled,&adc_fault,&foc_fault,&port.ODR,&tim.CCER};
    for(unsigned n=0;n<sizeof guards/sizeof *guards;++n){
        *guards[n]=1;DobWarmupAb_Command("MOTOR TEST MECH DOB WARM SET 5",out,sizeof out);
        assert(strstr(out,"ERR")&&dob_warmup_tau==3);*guards[n]=0;
    }
    tim.BDTR=TIM_BDTR_MOE;DobWarmupAb_Command("MOTOR TEST MECH DOB WARM SET 5",out,sizeof out);
    assert(strstr(out,"ERR")&&dob_warmup_tau==3);tim.BDTR=TIM_BDTR_AOE;
    DobWarmupAb_Command("MOTOR TEST MECH DOB WARM SET 5",out,sizeof out);assert(strstr(out,"ERR"));tim.BDTR=0;
    cl_session.state=0;DobWarmupAb_Command("MOTOR TEST MECH DOB WARM SET 5",out,sizeof out);assert(strstr(out,"ERR"));
    cl_session.state=CL_READY;DobWarmupAb_Command("MOTOR TEST MECH DOB WARM SET 4",out,sizeof out);assert(strstr(out,"ERR"));
    DobWarmupAb_Command("MOTOR TEST MECH DOB WARM SET 5",out,sizeof out);assert(dob_warmup_tau==5);
}
static uint32_t first_valid[2];
static void compare(void){
    MechanicalDobShadow s[2];memset(s,0,sizeof s);
    for(unsigned n=0;n<1000;++n){
        for(unsigned j=0;j<2;++j){
            dob_warmup_tau=j?5:3;
            MechanicalDob_Observe(&s[j],&mechanical_dob_identified_model,.16f+(n>500?.02f:0),25.13f,.001f,1,0);
            if(s[j].valid&&!first_valid[j])first_valid[j]=n;
        }
        assert(s[0].omega_lpf==s[1].omega_lpf&&s[0].drive_lpf==s[1].drive_lpf&&
            s[0].disturbance_a==s[1].disturbance_a&&s[0].elapsed_s==s[1].elapsed_s);
    }
    assert(first_valid[0]==239&&first_valid[1]==398);
    dob_warmup_tau=4;MechanicalDob_Observe(&s[0],&mechanical_dob_identified_model,.16f,25,.001f,1,0);
    assert(!s[0].valid&&s[0].status==DOB_SHADOW_UNCONFIGURED);
}
static void actual_monitor(unsigned tau){
    dob_warmup_tau=tau;DobNormal_Lifecycle(&mechanical_dob_monitor,&dob_feedback,1,0);
    uint32_t t=100000,seq=0;float before=0,elapsed=0;
    for(unsigned n=0;n<1200;++n){
        t+=1000;seq+=20;
        MechanicalCurrent c={.seq=seq,.source_us=t,.published_us=t+5,.id=n==900?.7f:.001f,.iq=.16f};
        MechanicalDobMonitor_Observe(&mechanical_dob_monitor,t+20,t,1000,25.13f,0,&c,1);
        if(n==899){before=mechanical_dob_monitor.abs_id_lpf;elapsed=mechanical_dob_monitor.observer.elapsed_s;}
        if(n==900)assert(mechanical_dob_monitor.abs_id_lpf==before&&mechanical_dob_monitor.observer.elapsed_s==elapsed);
    }
    assert(mechanical_dob_monitor.current.valid&&mechanical_dob_monitor.abs_id_lpf<.002f);
    DobNormal_Lifecycle(&mechanical_dob_monitor,&dob_feedback,0,1);
    assert(!mechanical_dob_monitor.current.valid&&!mechanical_dob_monitor.observer.initialized);
}
int main(void){
    assert(dob_warmup_tau==DOB_WARMUP_DEFAULT_TAU);command_guard();compare();actual_monitor(3);actual_monitor(5);
    puts("PASS: 239/398 ms; identical filter/estimate math; idle guards; 700mA spike excluded; fault reset retained");return 0;
}
