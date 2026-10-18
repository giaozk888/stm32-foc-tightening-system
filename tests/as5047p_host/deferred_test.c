/* Exercise the production deferred bottom half with the real protocol engine.
 * Simulation time is NOT an MCU WCET measurement. No hardware is accessed. */
#include "as5047p_dma_engine.h"
#include "as5047p_protocol.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#define CHECK(c) do { if (!(c)) { fprintf(stderr,"line %d: %s\n",__LINE__,#c); exit(1); } } while (0)
#define FOC_RAM_PATH
#define __DMB() ((void)0)
typedef struct { uint32_t CNT,DIER,SR,CCR1,CCR2,CCR3,CCR4,BDTR; } Timer;
typedef struct { uint32_t ISR,IFCR; } Dma;
typedef struct { uint32_t SR; } Spi;
typedef struct { uint32_t BSRR; } Gpio;
static Timer timer,pwm;
static Dma dma;
static Spi spi;
static Gpio gpio;
#define TIM2 (&timer)
#define TIM1 (&pwm)
#define DMA1 (&dma)
#define SPI1 (&spi)
#define DRIVER_SD_GPIO_Port (&gpio)
#define DRIVER_SD_Pin 64U
#define TIM_BDTR_MOE 32768U
#define TIM_BDTR_AOE 16384U
#define TIM_DIER_CC1IE 2U
#define TIM_DIER_CC2IE 4U
#define TIM_DIER_CC3IE 8U
#define TIM_DIER_CC4IE 16U
#define TIM_SR_CC1IF 2U
#define TIM_SR_CC2IF 4U
#define TIM_SR_CC3IF 8U
#define TIM_SR_CC4IF 16U
#define DMA_ISR_TEIF4 8U
#define DMA_ISR_TCIF4 2U
#define DMA_ISR_TEIF5 128U
#define DMA_IFCR_CGIF4 15U
#define DMA_IFCR_CGIF5 240U
#define SPI_SR_OVR 64U
#define SPI_SR_MODF 32U
#define SPI_SR_FRE 256U
#define TIM6_DAC_IRQn 54
static AsDmaEngine engine;
static unsigned periodic,service_pending,starts,finishes,off_seen;
static uint32_t next_period_us,control_due_us,word_started;
static uint32_t hold_until,inject_error,parity_error;
static uint32_t defer_fault_dma_isr,defer_fault_spi_sr;
static volatile uint32_t defer_fault_flags_valid;
static uint32_t defer_fault_serviced,timer_fault_reentry;
static void NVIC_SetPendingIRQ(int irq) { CHECK(irq==TIM6_DAC_IRQn); service_pending=1U; }
static void NVIC_ClearPendingIRQ(int irq) { CHECK(irq==TIM6_DAC_IRQn); service_pending=0U; }
static void StopWord(void *context) { (void)context; DMA1->ISR=0U; }
static void Compare(uint32_t *ccr,uint32_t flag,uint32_t due)
{ *ccr=due; TIM2->DIER|=flag; }
#include "as5047p_dma_deferred.inc"
static void Cs(void *p,int high) { (void)p; (void)high; }
static void Guard(void *p,uint32_t due) { (void)p; Compare(&timer.CCR2,4U,due); }
static void Deadline(void *p,int enabled,uint32_t due)
{ (void)p; if (enabled) Compare(&timer.CCR1,2U,due); else timer.DIER&=~2U; }
static int Start(void *p,volatile uint16_t *tx,volatile uint16_t *rx)
{ (void)p; (void)tx; (void)rx; ++starts; word_started=timer.CNT; return 1; }
static int Busy(void *p) { (void)p; return 0; }
static void Finish(void *p,AsDmaStatus status)
{
    (void)p; ++finishes; timer.DIER&=~4U;
    if (status!=AS_DMA_OK && status!=AS_DMA_CANCELLED) defer_fault_serviced=1U;
    if (status!=AS_DMA_OK) { periodic=0U; timer.DIER&=~(8U|16U); }
}
static void Fault(void *p,const AsDmaEngine *e,AsDmaStatus s,uint32_t now)
{
    (void)p; (void)e; (void)s; (void)now; off_seen=1U;
    if (timer_fault_reentry) { timer_fault_reentry=0U; DeferTimerTop(); }
}
static const AsDmaOps ops={Cs,Guard,Deadline,Start,StopWord,Busy,Finish,Fault};
static void Init(void)
{
    memset(&timer,0,sizeof(timer)); memset(&dma,0,sizeof(dma));
    memset(&spi,0,sizeof(spi)); memset(&pwm,0,sizeof(pwm));
    AsDma_Init(&engine,&ops,0); DeferReset();
    starts=finishes=off_seen=hold_until=inject_error=parity_error=timer_fault_reentry=0U;
    encoder_timer_event_count=encoder_rx_event_count=encoder_period_count=0U;
    periodic=1U; next_period_us=1000U; control_due_us=2500U;
    Compare(&timer.CCR3,8U,next_period_us); Compare(&timer.CCR4,16U,control_due_us);
    CHECK(AsDma_Begin(&engine,0x3fffU,0U));
}
static void Step(unsigned run_service)
{
    ++timer.CNT;
    if (((timer.DIER&2U) && timer.CNT==timer.CCR1) ||
        ((timer.DIER&4U) && timer.CNT==timer.CCR2) ||
        ((timer.DIER&8U) && timer.CNT==timer.CCR3) ||
        ((timer.DIER&16U) && timer.CNT==timer.CCR4)) DeferTimerTop();
    if (engine.state==AS_DMA_WORD && timer.CNT-word_started==4U) {
        uint16_t raw=(uint16_t)(1234U+engine.attempts);
        raw|=AS5047P_ParityIsOdd(raw) ? 0x8000U : 0U;
        if (parity_error && (engine.frame&1U)) raw^=0x8000U;
        engine.rx=raw; dma.ISR=inject_error ? DMA_ISR_TEIF4 : DMA_ISR_TCIF4;
        DeferRxTop();
    }
    if (run_service && service_pending && timer.CNT>=hold_until) {
        service_pending=0U; TIM6_DAC_IRQHandler();
    }
}
static void StepFocBlocked(unsigned phase)
{
    ++timer.CNT;
    if ((timer.DIER&2U) && timer.CNT==timer.CCR1) timer.SR|=2U;
    if ((timer.DIER&4U) && timer.CNT==timer.CCR2) timer.SR|=4U;
    if ((timer.DIER&8U) && timer.CNT==timer.CCR3) timer.SR|=8U;
    if ((timer.DIER&16U) && timer.CNT==timer.CCR4) timer.SR|=16U;
    if (engine.state==AS_DMA_WORD && timer.CNT-word_started==4U) {
        uint16_t raw=1234U;
        engine.rx=raw|(AS5047P_ParityIsOdd(raw) ? 0x8000U : 0U);
        dma.ISR=DMA_ISR_TCIF4;
    }
    /* Hardware flags latch while ADC owns the CPU. This tests all 50 phases
     * of a 35/50 us blackout, NOT the measured WCET of real ISR instructions. */
    if ((timer.CNT+phase)%50U<35U) return;
    if (dma.ISR&(DMA_ISR_TCIF4|DMA_ISR_TEIF4)) DeferRxTop();
    if (timer.SR&timer.DIER&30U) DeferTimerTop();
    if (service_pending) { service_pending=0U; TIM6_DAC_IRQHandler(); }
}
int main(void)
{
    Init(); for (unsigned i=0;i<30U;++i) Step(1U);
    CHECK(engine.sample.status==AS_DMA_OK && starts==2U && finishes==1U);
    CHECK(encoder_rx_event_count==2U && encoder_timer_event_count==5U);
    for (unsigned i=30U;i<2050U;++i) Step(1U);
    CHECK(engine.attempts==3U && engine.successes==3U && encoder_period_count==2U);
    CHECK(encoder_timer_event_count==17U); /* 5 initial CS events + 6/period */
    CHECK(!(timer.DIER&1U)); /* no UIF/UIE sample clock / duplicate sample bursts */
    Init(); hold_until=60U; for (unsigned i=0;i<120U;++i) Step(1U);
    CHECK(engine.sample.status==AS_DMA_OK && engine.sample.elapsed_us>=60U &&
          engine.sample.elapsed_us<AS_DMA_TRANSACTION_US);
    Init(); for (unsigned i=0;i<201U;++i) Step(0U);
    CHECK(defer_urgent==AS_DMA_TIMEOUT); TIM6_DAC_IRQHandler();
    CHECK(engine.sample.status==AS_DMA_TIMEOUT && off_seen && !periodic);
    uint32_t sequence=engine.sample.sequence; TIM6_DAC_IRQHandler();
    CHECK(engine.sample.sequence==sequence); /* first deferred fault handled once */
    Init(); timer.CNT=AS_DMA_TRANSACTION_US; timer_fault_reentry=1U;
    AsDma_CheckDeadline(&engine,timer.CNT); /* top half interrupts failure capture */
    CHECK(defer_urgent==AS_DMA_TIMEOUT && finishes==1U);
    sequence=engine.sample.sequence; TIM6_DAC_IRQHandler();
    CHECK(engine.sample.sequence==sequence && finishes==1U);
    Init(); control_due_us=3U; timer.CCR4=3U;
    for (unsigned i=0;i<5U;++i) Step(0U);
    CHECK(defer_urgent==AS_DMA_CONTROL_STALE); TIM6_DAC_IRQHandler();
    CHECK(engine.sample.status==AS_DMA_CONTROL_STALE && off_seen);
    Init(); inject_error=1U; for (unsigned i=0;i<30U;++i) Step(1U);
    CHECK(engine.sample.status==AS_DMA_IO && off_seen && !periodic);
    CHECK(defer_fault_flags_valid && (defer_fault_dma_isr&DMA_ISR_TEIF4));
    CHECK(defer_fault_spi_sr==0U && DMA1->ISR==0U); /* pre-ack flags retained */
    Init(); parity_error=1U; for (unsigned i=0;i<30U;++i) Step(1U);
    CHECK(engine.sample.status==AS_DMA_PARITY && off_seen);
    Init(); DeferTimerTop(); periodic=0U; DeferReset();
    CHECK(!service_pending && !defer_urgent && !defer_rx_seq);
    AsDma_Fail(&engine,AS_DMA_CANCELLED,timer.CNT);
    dma.ISR=DMA_ISR_TCIF4; DeferRxTop(); TIM6_DAC_IRQHandler();
    CHECK(engine.sample.status==AS_DMA_CANCELLED); /* old-epoch RX cannot resurrect */
    Init(); engine.rx=5U; engine.state=AS_DMA_WORD; dma.ISR=DMA_ISR_TEIF5;
    DeferTxTop(); TIM6_DAC_IRQHandler(); CHECK(engine.sample.status==AS_DMA_IO);
    for (unsigned phase=0U;phase<50U;++phase) {
        Init(); for (unsigned t=0U;t<199U;++t) StepFocBlocked(phase);
        CHECK(engine.sample.status==AS_DMA_OK && engine.sample.elapsed_us<AS_DMA_TRANSACTION_US);
        CHECK(engine.attempts==1U && engine.successes==1U && starts==2U);
    }
    puts("PASS real deferred service / 1kHz two-word protocol / delays / same deadlines / parity / error / epoch");
}
