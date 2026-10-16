#include <assert.h>
#include <stdint.h>
#include <stdio.h>
typedef struct { volatile uint32_t CR1, DIER, SR, PSC, ARR, CNT, EGR; } Timer;
static Timer timer;
#define TIM7 (&timer)
#define TIM7_DAC_IRQn 55
#define TIM_SR_UIF 1U
#define TIM_EGR_UG 1U
#define TIM_DIER_UIE 1U
#define TIM_CR1_CEN 1U
#define TIM_CR1_URS 4U
#define TIM_CR1_OPM 8U
static unsigned delay, clocks, pending, enabled, cleared, no_clock;
static void NVIC_DisableIRQ(unsigned irq) { assert(irq==55); enabled=0; }
static void NVIC_EnableIRQ(unsigned irq) { assert(irq==55); enabled=1; }
static void HAL_NVIC_ClearPendingIRQ(unsigned irq)
{ assert(irq==55 && !timer.SR && !timer.DIER); pending=0; ++cleared; }
static void __DSB(void) { if (timer.EGR) { timer.EGR=0; clocks=0; } }
static void __NOP(void)
{ if (++clocks>=delay && !no_clock) { timer.SR|=TIM_SR_UIF; pending=1; } }
#include "switch_feedback_guard_stm32.h"
int main(void)
{
    for (unsigned d=1;d<=40;d++) {
        delay=d; no_clock=0; cleared=0; enabled=1; pending=1; timer.SR=1;
        assert(SwitchGuard_Prepare());
        assert(clocks==d && cleared==1 && !enabled && !pending);
        assert(!timer.CR1 && !timer.DIER && !timer.SR && timer.PSC==16999 && timer.ARR==1899);
        SwitchGuard_Arm();
        assert(enabled && timer.CR1==13 && timer.DIER==1 && !timer.SR);
    }
    no_clock=1; enabled=1; cleared=0;
    assert(!SwitchGuard_Prepare());
    assert(!enabled && !timer.CR1 && !timer.DIER && cleared==0 && clocks==1024);
    for (unsigned d=1;d<=40;d++) {
        delay=d; no_clock=0; cleared=0; enabled=1; pending=1; timer.SR=1;
        assert(SwitchFilteredGuard_Prepare());
        assert(clocks==d && cleared==1 && !enabled && !pending);
        assert(!timer.CR1 && !timer.DIER && !timer.SR && timer.PSC==169 && timer.ARR==24);
        SwitchFilteredGuard_Arm();
        assert(enabled && timer.CR1==5 && timer.DIER==1 && !timer.SR);
    }
    no_clock=1; enabled=1; cleared=0;
    assert(!SwitchFilteredGuard_Prepare());
    assert(!enabled && !timer.CR1 && !timer.DIER && cleared==0 && clocks==1024);
    puts("GUARD PREPARE PASS: delayed UG/UIF, stale pending cleared, timeout fail-closed");
}
