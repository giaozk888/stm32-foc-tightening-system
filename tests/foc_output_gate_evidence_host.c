#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include "foc_output_gate_evidence.h"
#define CHECK(x) do {if(!(x)){printf("FAIL line %d\n",__LINE__);return 1;}}while(0)
#define FOC_CURRENT_STEP_AB_DIAG 1
#define FOC_PROTECTED_CLOSED_LOOP 1
#define CL_RUNNING 2U
#define TIM_CR1_CEN 1U
#define TIM_BDTR_MOE (1U<<15)
#define TIM_BDTR_AOE (1U<<14)
#define DRIVER_SD_Pin (1U<<6)
static struct {volatile uint32_t ODR;} port;
static struct {volatile uint32_t BDTR,CR1,CCER,SR;} timer;
static struct {uint32_t CYCCNT;} dwt;
#define DRIVER_SD_GPIO_Port (&port)
static void OnTimerRead(void);
#define TIM1 (OnTimerRead(),&timer)
#define DWT (&dwt)
static struct {uint32_t state;} cl_session;
static uint32_t cl_armed,injected_seq_count,mask,dmb_count,partial_publish;
static uint32_t timer_reads,inject_transition;
static void OnTimerRead(void)
{
    if (inject_transition && ++timer_reads==2U) {
        ++injected_seq_count;cl_session.state=3U;
    }
}
static uint32_t __get_PRIMASK(void){return mask;}
static void __disable_irq(void){mask=1U;}
static void __set_PRIMASK(uint32_t m){mask=m;}
static uint32_t __get_IPSR(void){return 18U;}
static uint32_t AS5047P_DmaNowUs(void){return 1234U;}
static void Barrier(void);
#define __DMB Barrier
#include "foc_output_gate_evidence_binding.inc"
static void Barrier(void)
{
    /* First barrier must see unpublished COMPLETE fields, second published. */
    if ((dmb_count==0U && (cl_output_gate_evidence.valid ||
         cl_output_gate_evidence.ccer!=0x444U || cl_output_gate_evidence.seq_after!=700U)) ||
        (dmb_count==1U && cl_output_gate_evidence.valid!=1U)) partial_publish=1U;
    ++dmb_count;
}
int main(void)
{
    /* Exhaustive Boolean/register cases against the ORIGINAL predicate. */
    const uint32_t ccers[]={0U,0x555U,0x444U,0x1555U};
    for(unsigned running=0;running<2;++running)
    for(unsigned bits=0;bits<16;++bits)
    for(unsigned k=0;k<4;++k){
        unsigned cen=bits&1U,aoe=bits&2U,sd=bits&4U,moe=bits&8U;
        unsigned old=cen&&!aoe&&(running ? (sd&&moe&&ccers[k]==0x555U) : (!sd&&!moe&&!ccers[k]));
        CHECK((FocOutputGate_Mismatch(running,cen,aoe,sd,moe,ccers[k])==0U)==!!old);
    }
    CHECK(FocOutputGate_Mismatch(1,1,0,0,1,0x555)==FOC_GATE_SD);
    CHECK(FocOutputGate_Mismatch(1,1,0,1,0,0x555)==FOC_GATE_MOE);
    CHECK(FocOutputGate_Mismatch(1,1,0,1,1,0x444)==FOC_GATE_CCER);
    CHECK(FocOutputGate_Mismatch(1,0,1,1,1,0x555)==(FOC_GATE_CEN_OFF|FOC_GATE_AOE_ON));
    /* Startup before armed does not consume the first-failure record. */
    CHECK(!ProtectedLoop_GatesObserved());CHECK(!cl_output_gate_evidence.valid);
    cl_session.state=CL_RUNNING;cl_armed=1U;timer.CR1=1U;
    timer.BDTR=TIM_BDTR_MOE;timer.CCER=0x555;port.ODR=DRIVER_SD_Pin;
    CHECK(ProtectedLoop_GatesObserved());CHECK(!cl_output_gate_evidence.valid);
    CHECK(!dmb_count && !mask);
    injected_seq_count=700U;dwt.CYCCNT=12345U;timer.CCER=0x444;timer.SR=0x81U;
    CHECK(!ProtectedLoop_GatesObserved());
    CHECK(cl_output_gate_evidence.valid && cl_output_gate_evidence.version==1U);
    CHECK(cl_output_gate_evidence.mismatch==FOC_GATE_CCER && !mask);
    CHECK(cl_output_gate_evidence.bdtr_moe_read==TIM_BDTR_MOE);
    CHECK(cl_output_gate_evidence.odr==DRIVER_SD_Pin && cl_output_gate_evidence.sr==0x81);
    CHECK(cl_output_gate_evidence.state_used==CL_RUNNING);
    CHECK(cl_output_gate_evidence.ipsr==18U && cl_output_gate_evidence.timer_us==1234U);
    CHECK(dmb_count==2U && !partial_publish);
    FocOutputGateEvidence first=cl_output_gate_evidence;
    /* Existing EmergencyOff erases registers; neither it nor later faults
     * may erase/overwrite the stored original predicate inputs. */
    port.ODR=0;timer.BDTR=timer.CCER=timer.CR1=0;injected_seq_count=900U;
    CHECK(!ProtectedLoop_GatesObserved());
    CHECK(!memcmp((const void *)&cl_output_gate_evidence,&first,sizeof first));
    /* IRQ mask already held by caller is preserved on the latch path. */
    memset((void *)&cl_output_gate_evidence,0,sizeof cl_output_gate_evidence);
    mask=1;dmb_count=10U;
    CHECK(!ProtectedLoop_GatesObserved());CHECK(mask==1U);
    CHECK(cl_output_gate_evidence.valid && cl_output_gate_evidence.primask==1U);
    /* Simulate ADC/session preemption between the read-only register loads.
     * Observer must expose torn context, not report a coherent RUNNING check. */
    memset((void *)&cl_output_gate_evidence,0,sizeof cl_output_gate_evidence);
    mask=0;cl_session.state=CL_RUNNING;injected_seq_count=700U;
    port.ODR=DRIVER_SD_Pin;timer.BDTR=TIM_BDTR_MOE;timer.CR1=1;timer.CCER=0x555;
    timer_reads=0;inject_transition=1;
    CHECK(!ProtectedLoop_GatesObserved());
    CHECK(cl_output_gate_evidence.state_before==CL_RUNNING);
    CHECK(cl_output_gate_evidence.state_used==3U && cl_output_gate_evidence.state_after==3U);
    CHECK(cl_output_gate_evidence.seq_before==700U && cl_output_gate_evidence.seq_after==701U);
    CHECK(cl_output_gate_evidence.mismatch==(FOC_GATE_SD|FOC_GATE_MOE|FOC_GATE_CCER));
    puts("PASS gate evidence: equivalent predicate, before-off, first-only, valid-last, mask restore");
    return 0;
}
