/* Execute the real reference/command binding, no peripheral or scheduler. */
#include <stdint.h>
#include <stddef.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdarg.h>
#include <math.h>
#include "current_step_ab.h"
#define CHECK(x) do{if(!(x)){fprintf(stderr,"CHECK %d: %s\n",__LINE__,#x);exit(2);}}while(0)
enum {CL_READY=1,CL_RUNNING=2,MOTOR_MODE_IDLE=0,MOTOR_MODE_IQ=1};
#define TIM_BDTR_MOE 0x8000U
#define TIM_BDTR_AOE 0x4000U
#define FOC_RUNDOWN240_IQ_LIMIT_A .50f
#define taskENTER_CRITICAL() ((void)0)
#define taskEXIT_CRITICAL() ((void)0)
typedef struct {uint32_t ODR;} Port;
typedef struct {uint32_t BDTR,CCER;} Timer;
static Port port;static Timer timer;
#define DRIVER_SD_GPIO_Port (&port)
#define DRIVER_SD_Pin 64U
#define TIM1 (&timer)
static CurrentStepAB current_step_ab;
static unsigned current_step_pi_new=1U;
static struct {unsigned state,used;} cl_session;
static struct {uint32_t source_us;} cl_frame;
static uint32_t cl_seq,cl_flags,cl_outer_n;
static unsigned adc_fault,foc_fault,motor_control_mode,tightening_start_request,tightening_stop_request;
static unsigned encoder_valid=1U;
static float encoder_speed_rpm,encoder_omega_e_rad_s;
static float foc_id_ref_A,foc_iq_ref_A,foc_int_d_V,foc_int_q_V;
static float foc_iq_A,foc_id_A,foc_vq_V,foc_vd_V,current_step_out_q,current_step_out_d;
static unsigned current_step_saturated;
static unsigned stop_count,invalidate_count,reset_count;
static int ProtectedLoop_Ready(void){return !adc_fault&&!foc_fault;}
static int Tightening_IsBusy(void){return 0;}
static void ProtectedLoop_Stop(void){++stop_count;cl_session.state=3;timer.BDTR=timer.CCER=port.ODR=0;}
static void ProtectedLoop_PwmInvalidate(void){++invalidate_count;}
static void FocCurrentPi_Reset(float *d,float *q){*d=*q=0;++reset_count;}
static int Protocol_SendFormatted(char *buf,size_t size,const char *fmt,...)
{va_list ap;va_start(ap,fmt);int r=vsnprintf(buf,size,fmt,ap);va_end(ap);return r;}
/* Only compile the actual command/reference/capture owner, not its RTOS task. */
#include "current_step_ab_test_binding.inc"
int main(void)
{
    char out[384];
    cl_session.state=CL_READY;motor_control_mode=MOTOR_MODE_IDLE;
    CHECK(CurrentStep_Command("MOTOR TEST PROFILE",out,sizeof out));
    CHECK(strstr(out,"FSM=BYPASSED"));
    port.ODR=DRIVER_SD_Pin;
    CHECK(CurrentStep_Command("MOTOR TEST CURRENT STEP AB CONFIRM",out,sizeof out));
    CHECK(!current_step_ab.used&&strstr(out,"ERR"));port.ODR=0;
    CHECK(CurrentStep_Command("MOTOR TEST CURRENT STEP AB CONFIRM",out,sizeof out));
    CHECK(current_step_ab.state==CS_QUEUED&&current_step_ab.used);
    CurrentStep_Begin(&current_step_ab,100U);cl_session.state=CL_RUNNING;
    motor_control_mode=MOTOR_MODE_IQ;cl_frame.source_us=100U;
    foc_int_d_V=foc_int_q_V=.5f;
    CHECK(CurrentStep_FocReference());CHECK(!foc_id_ref_A&&!foc_iq_ref_A);
    CHECK(reset_count==1U&&invalidate_count==1U&&!foc_int_d_V&&!foc_int_q_V);
    cl_frame.source_us=20100U;CHECK(CurrentStep_FocReference());
    CHECK(fabsf(foc_iq_ref_A-.1f)<1e-6f&&foc_id_ref_A==0.f);
    foc_iq_A=.1f;cl_seq=1U;CurrentStep_Capture();
    CHECK(current_step_ab.metrics[0].high_n==1U);
    CHECK(CurrentStep_Command("MOTOR TEST CURRENT STEP ROW 0",out,sizeof out));
    CHECK(strstr(out,"ACTIVE_OR_EMPTY"));
    foc_fault=1U;CHECK(!CurrentStep_FocReference());
    CHECK(stop_count==1U&&current_step_ab.state==CS_ABORT&&current_step_ab.reason==CS_PROTECTION);
    CHECK(!timer.CCER&&!timer.BDTR&&!port.ODR);
    CHECK(CurrentStep_Command("MOTOR TEST CURRENT STEP ROW 3",out,sizeof out));
    CHECK(strstr(out,"OK CS"));
    CHECK(CurrentStep_Command("MOTOR TEST CURRENT STEP METRIC 0",out,sizeof out));
    CHECK(strstr(out,"OK CSM"));
    foc_fault=0;cl_session.state=CL_READY;motor_control_mode=MOTOR_MODE_IDLE;
    CHECK(CurrentStep_Command("MOTOR TEST CURRENT STEP AB CONFIRM",out,sizeof out));
    CHECK(strstr(out,"ERR"));
    CHECK(!CurrentStep_Command("OTHER",out,sizeof out));
    puts("PASS actual step binding admission, neutral, PI reset, record, protection, no retry");
    return 0;
}
