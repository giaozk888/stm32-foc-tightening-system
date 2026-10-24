#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
static float dob_gain_ab=.25f;
#define DOB_FB_GAIN dob_gain_ab
#include "dob_feedback_candidate.h"
static DobFeedbackCandidate dob_feedback;
static unsigned busy,tightening_start_request,tightening_stop_request,motor_control_mode,adc_fault,foc_fault;
static struct {unsigned ODR;} driver;
static struct {unsigned BDTR,CCER;} timer;
#define DRIVER_SD_GPIO_Port (&driver)
#define DRIVER_SD_Pin 64U
#define TIM1 (&timer)
#define TIM_BDTR_MOE 32768U
#define TIM_BDTR_AOE 16384U
#define MOTOR_MODE_IDLE 0U
#define taskENTER_CRITICAL() ((void)0)
#define taskEXIT_CRITICAL() ((void)0)
static unsigned Tightening_IsBusy(void){return busy;}
#include "dob_gain_ab_binding.inc"
int main(void){
 char out[192];
 assert(!DobGainAb_Command("OTHER",out,sizeof out));
 assert(DobGainAb_Command("MOTOR TEST MECH DOB FB GAIN 250001",out,sizeof out));
 assert(strstr(out,"ERR")&&dob_gain_ab==.25f);
 for(unsigned i=0;i<10;i++){
  busy=tightening_start_request=tightening_stop_request=motor_control_mode=adc_fault=foc_fault=driver.ODR=timer.BDTR=timer.CCER=0;
  switch(i){case 0:busy=1;break;case 1:tightening_start_request=1;break;case 2:tightening_stop_request=1;break;
  case 3:motor_control_mode=1;break;case 4:driver.ODR=64;break;case 5:timer.BDTR=32768;break;
  case 6:timer.BDTR=16384;break;case 7:timer.CCER=1;break;case 8:adc_fault=1;break;default:foc_fault=1;}
  dob_feedback.enabled=1;dob_feedback.iq_comp_a=.01f;
  assert(DobGainAb_Command("MOTOR TEST MECH DOB FB GAIN 500000",out,sizeof out));
  assert(strstr(out,"ERR DOBGAIN")&&dob_gain_ab==.25f&&dob_feedback.enabled&&dob_feedback.iq_comp_a==.01f);
 }
 busy=tightening_start_request=tightening_stop_request=motor_control_mode=adc_fault=foc_fault=driver.ODR=timer.BDTR=timer.CCER=0;
 for(unsigned g=0;g<2;g++){
  assert(DobGainAb_Command(g?"MOTOR TEST MECH DOB FB GAIN 500000":"MOTOR TEST MECH DOB FB GAIN 250000",out,sizeof out));
  assert(!dob_feedback.enabled&&dob_feedback.iq_comp_a==0);
  assert(dob_gain_ab==(g?.5f:.25f));
  dob_feedback.enabled=1;
  for(uint32_t t=1000;t<=200000;t+=1000)
   DobFeedback_Update(&dob_feedback,t,1000,t,.02f,1,1,.5f);
  assert(fabsf(dob_feedback.iq_comp_a-(g?.01f:.005f))<1e-6f);
  for(uint32_t t=201000;t<=500000;t+=1000)
   assert(fabsf(DobFeedback_Update(&dob_feedback,t,1000,t,1.f,1,1,.5f))<=.025f);
 }
 puts("PASS: exact gains, idle/fault/output guards, reset-to-OFF, signed mapping and unchanged cap");
 return 0;
}
