/* Execute the actual STM32 binding against register/task mocks. This proves
 * software ordering and failure policy, not motor/driver electrical timing. */
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>
#if defined(FOC_FAST_CURRENT_REJECT)
#include <stdarg.h>
static struct { uint32_t DEMCR; } mock_coredebug;
#define CoreDebug (&mock_coredebug)
#define CoreDebug_DEMCR_TRCENA_Msk (1U<<24)
static uint32_t SystemCoreClock=170000000U;
static char validation_log[480];
static void UART_SendFormatted(char *buffer,size_t size,const char *format,...) {
    va_list args; va_start(args,format); vsnprintf(buffer,size,format,args); va_end(args);
    snprintf(validation_log,sizeof(validation_log),"%s",buffer);
}
#define TWO_PI_F 6.28318530718f
#define FOC_TS_S 0.00005f
static float encoder_omega_e_rad_s;
#endif
#include "protected_closed_loop.h"
#include "foc_adc_window.h"
#if defined(FOC_LATEST_ORIGINAL_FSM)
/* Deterministic CI failure, not a Windows CRT assertion dialog. */
#undef assert
#define assert(condition) do { if (!(condition)) { \
    fprintf(stderr,"assertion failed: %s:%d: %s\n",__FILE__,__LINE__,#condition); \
    exit(101); } } while (0)
#endif
typedef struct { volatile uint32_t CR1,DIER,SR,PSC,ARR,CNT,EGR,BDTR,CCER,CCR1; } Timer;
typedef struct { volatile uint32_t ODR,BSRR; } Gpio;
typedef struct { volatile uint32_t CFGR,APB1ENR1; } Clock;
static Timer t1,t2,t7;
static Gpio gpio;
static Clock clock_regs;
#define TIM1 (&t1)
#define TIM2 (&t2)
#define TIM7 (&t7)
#define RCC (&clock_regs)
#define DRIVER_SD_GPIO_Port (&gpio)
#define DRIVER_SD_Pin (1U<<6U)
#define TIM7_DAC_IRQn 55U
#define ADC1_2_IRQn 18U
#define TIM2_IRQn 28U
#define DMA1_Channel4_IRQn 14U
#define DMA1_Channel5_IRQn 15U
#define TIM_CR1_CEN 1U
#define TIM_CR1_URS 4U
#define TIM_CR1_OPM 8U
#define TIM_SR_UIF 1U
#define TIM_DIER_UIE 1U
#define TIM_EGR_UG 1U
#define TIM_BDTR_MOE (1U<<15U)
#define TIM_BDTR_AOE (1U<<14U)
#define RCC_CFGR_PPRE1 4U
#define RCC_APB1ENR1_TIM2EN 1U
#define RCC_APB1ENR1_TIM7EN 32U
#define ADC_FULL_SCALE 4095U
#define ADC_VREF_MV 3300U
#define CURRENT_GAIN_MV_PER_A 120U
#define FOC_CURRENT_TRIP_A 4.0f
#define MOTOR_MODE_IDLE 0U
#define MOTOR_MODE_SPEED 2U
#define pdMS_TO_TICKS(x) (x)
#define __HAL_RCC_TIM7_CLK_ENABLE() (clock_regs.APB1ENR1 |= RCC_APB1ENR1_TIM7EN)
typedef int HAL_StatusTypeDef;
#define HAL_OK 0
#define HAL_BUSY 2
#define HAL_ERROR 1
static uint32_t mask,enabled,adc_priority,guard_priority;
static uint32_t encoder_priorities[3];
static uint8_t adc_fault,foc_fault,foc_enable,analog_safe_latched,encoder_valid;
static uint8_t run_zero_cal_done,current_filter_enable,tightening_start_request;
static uint8_t motor_control_mode,trial,periodic,planner_ok=1U,encoder_ok=1U;
static uint8_t meta_valid=1U;
static uint32_t metadata_reads;
static uint32_t prepared_commits, prepare_interrupt, prepare_calls;
#if defined(FOC_GUARD_FAST_PATH)
static uint8_t mock_sd_ignore_next_reset;
#endif
static void ProtectedLoop_Stop(void);
#define APP_THIS_SLOT 2U
#define BOOT_SLOT_NONE 0U
typedef struct { uint32_t confirmed_slot,pending_slot,attempts_left; } BootMetaV3_t;
static uint8_t BootMeta_ReadV3(BootMetaV3_t *out)
{
    assert(!mask && !enabled); /* Foreground before independent guard only. */
    ++metadata_reads;
    *out=(BootMetaV3_t){trial ? 1U : APP_THIS_SLOT,trial ? APP_THIS_SLOT : BOOT_SLOT_NONE,trial ? 1U : 0U};
    return meta_valid;
}
static uint32_t injected_seq_count,foc_fault_reason,idle_calls;
static uint16_t iu_zero_raw,iv_zero_raw;
static uint16_t analog_vdda_boot_mv=3300U;
static uint8_t analog_vdda_boot_valid=1U;
static float foc_id_ref_A,foc_iq_ref_A,encoder_theta_e_pred,encoder_theta_e;
static float encoder_speed_rpm,speed_request;
#if defined(FOC_STARTUP_TRACE)
static struct { uint32_t sample_us; } encoder_dma_cursor;
static uint16_t encoder_raw;
static float speed_ref_rpm,encoder_rpm_instant,foc_id_A,foc_iq_A;
static void ProtectedLoop_StartupInjectedFault(void);
#endif
#if defined(FOC_LATEST_ORIGINAL_FSM)
static uint8_t tightening_stop_request,mock_tightening_busy;
static uint32_t tightening_stop_request_id;
static volatile float foc_int_d_V,foc_int_q_V,foc_vd_V,foc_vq_V;
#endif
static struct { uint8_t active; } fw_update;
static uint32_t __get_PRIMASK(void) { return mask; }
#if defined(FOC_FAST_MATH)
#include "foc_irq_load.h"
static struct { uint32_t CYCCNT,CTRL; } mock_dwt={0U,1U};
#define DWT (&mock_dwt)
#define DWT_CTRL_CYCCNTENA_Msk 1U
static FocIrqLoad load;
void FocIrqLoad_Enter(void) { FocIrqLoad_Begin(&load,0U); }
void FocIrqLoad_Leave(void) { FocIrqLoad_End(&load,1U); }
#if defined(FOC_IRQ_SOURCE_TRACE)
static FocIrqSources source_load;
void FocIrqSource_Enter(unsigned id) { FocIrqLoad_Enter(); FocIrqSources_Enter(&source_load,id,0U); }
void FocIrqSource_Leave(unsigned id) { FocIrqLoad_Leave(); FocIrqSources_Leave(&source_load,id,1U); }
void FocIrqSource_FrameBegin(void) { FocIrqSources_FrameBegin(&source_load); }
void FocIrqSource_FrameEnd(FocIrqSourceFrame *out) { FocIrqSources_FrameEnd(&source_load,out); }
void FocIrqSource_Stats(FocIrqSourceStats *out) { *out=source_load.stats; }
#endif
#endif
static void __disable_irq(void) { mask=1U; }
static void __set_PRIMASK(uint32_t x) { mask=x; }
static void __DMB(void) { }
static void __DSB(void)
{
    gpio.ODR |= gpio.BSRR & 0xffffU;
#if defined(FOC_GUARD_FAST_PATH)
    if (mock_sd_ignore_next_reset && (gpio.BSRR>>16U)&DRIVER_SD_Pin) {
        gpio.BSRR&=~(DRIVER_SD_Pin<<16U);
        mock_sd_ignore_next_reset=0U;
    }
#endif
    gpio.ODR &= ~(gpio.BSRR>>16U); gpio.BSRR=0U;
    if (t7.EGR) { t7.EGR=0U; t7.SR|=TIM_SR_UIF; }
}
static void __NOP(void) { }
static void NVIC_DisableIRQ(unsigned irq) { assert(irq==55U); enabled=0U; }
static void NVIC_EnableIRQ(unsigned irq) { assert(irq==55U); enabled=1U; }
static uint32_t NVIC_GetEnableIRQ(unsigned irq) { assert(irq==55U); return enabled; }
static uint32_t NVIC_GetPriority(unsigned irq)
{
    if (irq==TIM2_IRQn) return encoder_priorities[0];
    if (irq==DMA1_Channel4_IRQn) return encoder_priorities[1];
    if (irq==DMA1_Channel5_IRQn) return encoder_priorities[2];
    return irq==55U ? guard_priority : adc_priority;
}
static void NVIC_ClearPendingIRQ(unsigned irq) { assert(irq==55U); }
static void HAL_NVIC_SetPriority(unsigned irq,unsigned p,unsigned sub)
{ assert(!sub); if (irq==55U) guard_priority=p; else adc_priority=p; }
static uint32_t HAL_RCC_GetPCLK1Freq(void) { return 85000000U; }
#if defined(FOC_GATE_REUSE)
static unsigned break_on_time_call;
#endif
static uint32_t AS5047P_DmaNowUs(void)
{
#if defined(FOC_GATE_REUSE)
    if (break_on_time_call && !--break_on_time_call) t1.BDTR&=~TIM_BDTR_MOE;
#endif
    return t2.CNT;
}
static uint32_t HAL_GetTick(void) { return t2.CNT/1000U; }
static int AS5047P_DmaStartPeriodic(void) { periodic=1U; return 1; }
static int AS5047P_DmaIsPeriodic(void) { return periodic; }
static void AS5047P_DmaStopPeriodic(void) { periodic=0U; }
static int FocAdcTiming_Commit(float a,float b,float c)
{ assert(a>=0.0f && b>=0.0f && c>=0.0f);
#if defined(FOC_PWM_PIPELINE_CLOSED_LOOP)
    t1.CCR1=2125U;
#else
    t1.CCR1=2124U;
#endif
    return planner_ok ? 0 : 1; }
static int FocAdcTiming_CertifyClock(void) { return planner_ok; }
#if defined(FOC_ONE_CYCLE_PWM_PIPELINE)
static unsigned pipeline_guard_probe,pipeline_adc_preempt;
static void PipelineMock_AdcProgress(void);
#endif
static int FocAdcTiming_FastCanStart(void) {
#if defined(FOC_ONE_CYCLE_PWM_PIPELINE)
    if (pipeline_guard_probe) {
        assert(!mask); /* Read-only TIM7 health is preemptible by ADC. */
        if (pipeline_adc_preempt) { pipeline_adc_preempt=0U; PipelineMock_AdcProgress(); }
    }
#endif
    return planner_ok;
}
static FocWindowStatus FocAdcTiming_Prepare(float a,float b,float c,FocWindowPlan *out)
{
    ++prepare_calls;
    assert(!mask && a>=0.0f && b>=0.0f && c>=0.0f);
    *out=(FocWindowPlan){0};
#if defined(FOC_ONE_CYCLE_PWM_PIPELINE)
    out->phase[0]=(uint16_t)(a*4249.0f);
    out->phase[1]=(uint16_t)(b*4249.0f);
    out->phase[2]=(uint16_t)(c*4249.0f);
#endif
    if (prepare_interrupt==1U) ProtectedLoop_EmergencyOff(CL_BAD_ADC);
    if (prepare_interrupt==2U) ProtectedLoop_Stop();
    return planner_ok ? FOC_WINDOW_OK : FOC_WINDOW_BAD_ARGUMENT;
}
static void FocAdcTiming_CommitPrepared(const FocWindowPlan *out)
{ assert(mask && out); ++prepared_commits; }
static void FocAdcTiming_PlanFailed(FocWindowStatus status)
{ assert(mask && status!=FOC_WINDOW_OK); }
static int UART_Async_IsReady(void) { return 1; }
static int Tightening_IsBusy(void) {
#if defined(FOC_LATEST_ORIGINAL_FSM)
    return mock_tightening_busy;
#else
    return 0;
#endif
}
static void MotorControl_SetIdle(void) { motor_control_mode=MOTOR_MODE_IDLE; ++idle_calls; }
static void MotorControl_SetSpeed(float x) { motor_control_mode=MOTOR_MODE_SPEED; speed_request=x; }
static void FOC_ResetController(void) { foc_id_ref_A=foc_iq_ref_A=0.0f; }
static HAL_StatusTypeDef FOC_EncoderSpeedUpdate(float dt)
{
    assert(dt==0.001f);
#if defined(FOC_STARTUP_TRACE)
    if (encoder_ok==3U) { ProtectedLoop_StartupInjectedFault(); return HAL_ERROR; }
#endif
    return encoder_ok==2U ? HAL_BUSY : encoder_ok ? HAL_OK : HAL_ERROR;
}
static void vTaskDelay(unsigned ms);
#if defined(FOC_TIMEOUT_DIAGNOSTICS)
#include "foc_timeout_diag.h"
static FocTimeoutReason encoder_timeout_reason;
static uint32_t tightening_test_stage,tightening_test_elapsed_ms;
static uint32_t tightening_contact_candidate_ms,encoder_error_count,foc_control_count;
static float encoder_position_deg,position_target_deg,position_error_deg,stall_timer_s;
#if !defined(FOC_STARTUP_TRACE)
static float speed_ref_rpm,encoder_rpm_instant,foc_id_A,foc_iq_A;
#endif
static char snapshot_log[8192];
static size_t snapshot_log_size;
static unsigned snapshot_tx_budget=1000U;
static uint8_t UART_SendReliableFormatted(char *buffer,size_t size,const char *format,...)
{
    assert(!mask); /* Formatting/queueing MUST stay outside writer critical section. */
    if (!snapshot_tx_budget) return 0U;
    --snapshot_tx_budget;
    va_list args; va_start(args,format);
    int n=vsnprintf(buffer,size,format,args); va_end(args);
    assert(n>0 && (size_t)n<size && snapshot_log_size+(size_t)n<sizeof(snapshot_log));
    memcpy(snapshot_log+snapshot_log_size,buffer,(size_t)n+1U);
    snapshot_log_size+=(size_t)n;
    return 1U;
}
#include "foc_fault_snapshot.inc"
#endif
#if defined(FOC_ONE_CYCLE_PWM_PIPELINE)
#define configPRIO_BITS 4U
#define configLIBRARY_MAX_SYSCALL_INTERRUPT_PRIORITY 5U
#define configMAX_SYSCALL_INTERRUPT_PRIORITY 0x50U
#include "foc_preempt_probe.h"
static uint32_t pending_commits;
static uint16_t committed_phase[3];
#if defined(FOC_PWM_PIPELINE_CLOSED_LOOP)
#define FOC_ADC_TIMER_ARR 4249U
static uint8_t pipeline_timing_ready=1U,pipeline_plan_matches=1U;
static int FocAdcTiming_PipelineActuationReady(void) { return pipeline_timing_ready; }
static int FocAdcTiming_PipelinePlanMatches(const FocWindowPlan *plan)
{ (void)plan; return pipeline_plan_matches; }
#endif
static int FocAdcTiming_PipelineCommit(const uint16_t phase[3])
{
#if defined(FOC_PWM_PIPELINE_CLOSED_LOOP)
    unsigned permit=ProtectedLoop_PwmCommitPermit();
    if (!permit) return 0;
    assert(permit==2U ? gpio.ODR==DRIVER_SD_Pin && t1.CCER==0x555U &&
        (t1.BDTR&TIM_BDTR_MOE) : !gpio.ODR && !t1.CCER && !(t1.BDTR&TIM_BDTR_MOE));
#else
    assert(phase && !gpio.ODR && !t1.CCER && !(t1.BDTR&TIM_BDTR_MOE));
#endif
    memcpy(committed_phase,phase,sizeof committed_phase); ++pending_commits; return 1;
}
static void FocAdcTiming_ProfileDutyPoint(void) { }
FocPreToken FocPreempt_IrqBegin(unsigned source)
{ (void)source; return (FocPreToken){0}; }
void FocPreempt_IrqEnd(unsigned source,FocPreToken token) { (void)source; (void)token; }
uint32_t FocPreempt_End(uint32_t start,uint32_t path)
{ (void)path; return DWT->CYCCNT-start; }
void FocPreempt_CheckPriorities(void) { }
void FocPreempt_Monitor(void) { }
#endif
#include "protected_closed_loop.inc"
#if defined(FOC_ONE_CYCLE_PWM_PIPELINE)
static void PipelineMock_AdcProgress(void)
{
    ++cl_seq; injected_seq_count=cl_seq; t2.CNT+=50U; cl_last_us=t2.CNT;
}
#endif
#if defined(FOC_STARTUP_TRACE)
static void ProtectedLoop_StartupInjectedFault(void)
{ ProtectedLoop_EmergencyOff(CL_OVERSPEED); }
#endif
static void tick(void) { t2.CNT+=25U; t7.SR=TIM_SR_UIF; TIM7_DAC_IRQHandler(); }
static int pair(uint16_t u,uint16_t v)
{
    tick(); tick(); ++injected_seq_count;
    int ready=ProtectedLoop_Pair(u,v);
    if (ready) ProtectedLoop_WorkEnd(t2.CNT-30U);
    return ready;
}
static void vTaskDelay(unsigned ms)
{ for (unsigned i=0;i<ms*20U;++i) (void)pair(1551U,1551U); }
static void reset(void)
{
    t1=(Timer){0}; t2=(Timer){.CR1=1U,.PSC=169U,.ARR=UINT32_MAX,.CNT=100U}; t7=(Timer){0};
    gpio=(Gpio){0}; clock_regs=(Clock){.CFGR=4U,.APB1ENR1=1U};
    mask=enabled=adc_priority=guard_priority=0U;
#if defined(AS5047P_DMA_FOC_FIRST)
    encoder_priorities[0]=encoder_priorities[1]=encoder_priorities[2]=3U;
#else
    encoder_priorities[0]=encoder_priorities[1]=encoder_priorities[2]=1U;
#endif
    adc_fault=foc_fault=foc_enable=analog_safe_latched=run_zero_cal_done=current_filter_enable=0U;
    tightening_start_request=motor_control_mode=trial=periodic=0U;
    meta_valid=1U; metadata_reads=0U; cl_boot_confirmed=0U;
    prepared_commits=prepare_interrupt=prepare_calls=0U;
    injected_seq_count=foc_fault_reason=idle_calls=0U;
    encoder_valid=planner_ok=encoder_ok=analog_vdda_boot_valid=1U;
    encoder_speed_rpm=encoder_theta_e_pred=encoder_theta_e=0.0f;
    fw_update.active=0U; cl_session=(ClSession){0}; cl_safety=(FocFeedbackSafety){0};
    cl_seq=cl_last_us=cl_guard_us=cl_irqs=cl_work_n=cl_work_max=cl_late=cl_outer_n=cl_off_us=0U;
    cl_stop_us=cl_fault_seq=cl_fault_last_us=cl_flags=0U;
    cl_fault_u=cl_fault_v=cl_last_u=cl_last_v=0U;
    cl_armed=cl_initialized=cl_fault_valid=cl_request=0U;
#if defined(FOC_TIMEOUT_DIAGNOSTICS)
    FaultDiag_Clear(); current_hold_total=0U;
    current_hold_window=(FocHoldWindow){0}; cl_direct_timeout=(FocTimeoutEvidence){0};
    encoder_timeout_reason=FOC_TO_NONE;
    snapshot_log_size=0U; snapshot_log[0]=0; snapshot_tx_budget=1000U;
#endif
}
static void ready(void)
{
    reset(); assert(ProtectedLoop_Init());
    assert(cl_session.state==CL_READY && !gpio.ODR && !t1.CCER && !(t1.BDTR&TIM_BDTR_MOE));
    for (unsigned i=0;i<10U;++i) (void)pair(1551U,1551U);
    assert(!periodic && !ProtectedLoop_Ready());
    ProtectedLoop_TaskService(); assert(periodic && !ProtectedLoop_Ready());
    ProtectedLoop_TaskService(); assert(ProtectedLoop_Ready());
}
static void run(void)
{
    char text[192]; ready(); ProtectedLoop_Command("MOTOR TEST SPEED",text,sizeof text);
    assert(strstr(text,"QUEUED=1") && !gpio.ODR && !t1.CCER);
    ProtectedLoop_TaskService();
    assert(cl_session.state==CL_RUNNING && speed_request==20.0f && gpio.ODR==DRIVER_SD_Pin && t1.CCER==0x555U);
}
static void off(void)
{ assert(!gpio.ODR && !t1.CCER && !(t1.BDTR & (TIM_BDTR_MOE|TIM_BDTR_AOE))); }
int main(int argc,char **argv)
{
    assert(argc==2); unsigned n=(unsigned)atoi(argv[1]); char text[192];
    switch (n) {
    case 0: ready(); assert(!cl_session.used && !cl_session.queued); break;
    case 1: run(); ProtectedLoop_Command("STOP",text,sizeof text); off();
        assert(cl_session.state==CL_DONE && cl_session.used);
        ProtectedLoop_Command("MOTOR TEST SPEED",text,sizeof text); assert(strstr(text,"REJECTED")); break;
    case 2: run();
        while (cl_session.state==CL_RUNNING) {
            (void)pair(1551U,1551U);
            if (injected_seq_count%20U==0U) ProtectedLoop_TaskService();
        }
        off(); assert(cl_session.state==CL_DONE && !foc_fault &&
            cl_stop_us-cl_session.start_us>=400000U && cl_stop_us-cl_session.start_us<=400025U); break;
    case 3: run(); for (unsigned i=0;i<5U;++i) tick(); off();
        assert(cl_session.state==CL_FAULT && (cl_flags & CL_BAD_ADC)); break;
    case 4: run(); cl_session.outer_us=t2.CNT-2001U; tick(); off(); assert(cl_flags & CL_OUTER_STALE); break;
    case 5: run(); encoder_speed_rpm=61.0f; tick(); off(); assert(cl_flags & CL_OVERSPEED); break;
    case 6: run(); ProtectedLoop_WorkEnd(t2.CNT-50U); off(); assert(cl_late && (cl_flags & CL_COMPUTE_LATE)); break;
    case 7: reset(); trial=1U; assert(ProtectedLoop_Init());
        for(unsigned i=0;i<10U;++i) (void)pair(1551U,1551U);
        ProtectedLoop_TaskService(); ProtectedLoop_TaskService();
        assert(!cl_boot_confirmed);
        ProtectedLoop_Command("MOTOR TEST SPEED",text,sizeof text); off();
        assert(strstr(text,"REJECTED") && !cl_session.used); break;
    case 8: ready(); ProtectedLoop_Command("MOTOR TEST SPEED",text,sizeof text);
        ProtectedLoop_Command("MOTOR TEST STOP",text,sizeof text); ProtectedLoop_TaskService(); off();
        assert(cl_session.state==CL_DONE); break;
    case 9: run(); for(unsigned i=0;i<10U && !foc_fault;++i) (void)pair(800U,1551U);
        off(); assert(cl_safety.protection.reason==FOC_FP_CONFIRMED_CURRENT); break;
    case 10: run(); (void)pair(800U,1551U); (void)pair(1551U,1551U); (void)pair(1551U,1551U);
        assert(!foc_fault && cl_safety.protection.repaired_pairs==1U); break;
    case 11: run(); t1.BDTR|=TIM_BDTR_AOE; tick(); off(); assert(cl_flags & CL_BAD_OUTPUT); break;
    case 12: run(); ProtectedLoop_EmergencyOff(CL_CORE_FAULT); uint32_t first=cl_off_us;
        t2.CNT+=300U; ProtectedLoop_EmergencyOff(CL_BAD_ADC); off(); assert(cl_off_us==first && cl_fault_valid);
        ProtectedLoop_Command("MOTOR TEST SPEED",text,sizeof text); assert(strstr(text,"REJECTED")); break;
    case 13: ready();
        for(unsigned i=0;i<8U;++i) {
            (void)pair(800U,1551U); for(unsigned j=0;j<3U;++j) (void)pair(1551U,1551U);
            if (foc_fault) break;
        }
        off(); assert(cl_safety.protection.reason==FOC_FP_REPAIR_BUDGET); break;
    case 14: ready();
        cl_irqs=cl_outer_n=cl_work_n=cl_work_max=cl_late=cl_flags=UINT32_MAX;
        cl_stop_us=UINT32_MAX; cl_zero.count=cl_zero.restarts=UINT32_MAX;
        cl_safety.protection.raw_pairs=cl_safety.protection.feedback_pairs=cl_safety.protection.repaired_pairs=UINT32_MAX;
        const char *commands[]={"MOTOR TEST STATUS","MOTOR TEST ZERO","MOTOR TEST PROTECTION","MOTOR TEST TIMING","MOTOR TEST FAULT"};
        for(unsigned i=0;i<5U;++i) {
            memset(text,0xa5,sizeof text); ProtectedLoop_Command(commands[i],text,sizeof text);
            assert(strlen(text)<sizeof text-1U);
        } break;
    case 15: {
        ClSession s={.state=CL_READY}; assert(ClSession_Queue(&s,1U));
        assert(ClSession_Start(&s,UINT32_MAX-100U,1U));
        assert(!ClSession_Expired(&s,(uint32_t)(s.start_us+399999U)));
        assert(ClSession_Expired(&s,(uint32_t)(s.start_us+400000U))); break;
    }
    case 16: run(); encoder_ok=0U; ProtectedLoop_TaskService(); off(); assert(cl_flags & CL_BAD_ENCODER); break;
    case 17: run(); t7.ARR=25U; tick(); off(); assert(cl_flags & CL_BAD_TIMER); break;
    case 18: run(); ProtectedLoop_Shutdown(); off();
        assert(!cl_armed && !foc_enable && !run_zero_cal_done && !(t1.CR1&TIM_CR1_CEN));
        assert(!enabled && !t7.DIER && cl_session.state==CL_DONE);
        ProtectedLoop_TaskService(); assert(!periodic);
        ProtectedLoop_Command("MOTOR TEST SPEED",text,sizeof text);
        assert(strstr(text,"REJECTED")); break;
    case 19: run(); encoder_ok=2U; uint32_t old_outer=cl_session.outer_us;
        ProtectedLoop_TaskService(); assert(!foc_fault && cl_session.outer_us==old_outer);
        cl_session.outer_us=t2.CNT-2001U; tick(); off(); assert(cl_flags&CL_OUTER_STALE); break;
    case 20: ready(); uint32_t old_count=cl_outer_n; encoder_ok=2U;
        ProtectedLoop_TaskService(); assert(!foc_fault && cl_outer_n==old_count);
        encoder_ok=1U; ProtectedLoop_TaskService(); assert(cl_outer_n==old_count+1U); break;
    case 21: run(); assert(metadata_reads==1U && cl_boot_confirmed);
        for(unsigned i=0;i<1000U;++i) {
            (void)pair(1551U,1551U);
            if(i%20U==0U) ProtectedLoop_TaskService();
        }
        assert(!foc_fault && metadata_reads==1U); break;
    case 22: reset(); meta_valid=0U; assert(ProtectedLoop_Init());
        for(unsigned i=0;i<10U;++i) (void)pair(1551U,1551U);
        ProtectedLoop_TaskService(); ProtectedLoop_TaskService();
        ProtectedLoop_Command("MOTOR TEST SPEED",text,sizeof text); off();
        assert(!cl_boot_confirmed && !cl_session.used && strstr(text,"REJECTED")); break;
    case 23: run(); cl_boot_confirmed=0U; tick(); off();
        assert(cl_flags&CL_BAD_ADMISSION); break;
    case 24: run(); uint32_t before=prepared_commits;
        ProtectedLoop_SetDuty(.6f,.4f,.5f); assert(prepared_commits==before+1U && !mask);
        prepare_interrupt=1U; ProtectedLoop_SetDuty(.6f,.4f,.5f); off();
        assert(prepared_commits==before+1U && !mask && cl_session.state==CL_FAULT); break;
    case 25: ready(); ProtectedLoop_Command("MOTOR TEST SPEED",text,sizeof text);
        prepare_interrupt=1U; ProtectedLoop_TaskService(); off();
        assert(!prepared_commits && !cl_session.started && cl_session.state==CL_FAULT); break;
    case 26: run(); before=prepared_commits; planner_ok=0U;
        ProtectedLoop_SetDuty(.6f,.4f,.5f); off();
        assert(prepared_commits==before && cl_flags&CL_BAD_ADC); break;
    case 27: run(); planner_ok=0U; tick(); off(); assert(cl_flags&CL_BAD_TIMER); break;
    case 28: run(); before=prepared_commits; prepare_interrupt=2U;
        ProtectedLoop_SetDuty(.6f,.4f,.5f); off();
        assert(prepared_commits==before && cl_session.state==CL_DONE && !foc_fault); break;
    case 29: ready(); ProtectedLoop_Command("MOTOR TEST SPEED",text,sizeof text);
        prepare_interrupt=2U; ProtectedLoop_TaskService(); off();
        assert(!prepared_commits && !cl_session.started && cl_session.state==CL_DONE && !foc_fault); break;
#if defined(AS5047P_DMA_IRQ_PREEMPT_ADC)
    case 30: ready(); assert(guard_priority==0U && adc_priority==2U);
        for (unsigned i=0U;i<3U;++i) {
            encoder_priorities[i]=3U;
            assert(!ProtectedLoop_TimerHealthy());
            encoder_priorities[i]=1U;
            assert(ProtectedLoop_TimerHealthy());
        }
        encoder_priorities[0]=3U; tick(); off(); assert(cl_flags&CL_BAD_TIMER); break;
#endif
#if defined(FOC_FAST_MATH)
    case 31: ready(); cl_cpu_max_cyc=cl_preempt_max_cyc=cl_pair_max_us=cl_math_max_us=UINT32_MAX;
        memset(text,0xa5,sizeof text); ProtectedLoop_Command("MOTOR TEST COST",text,sizeof text);
        assert(strstr(text,"TRIG=POLY9_8 DWT=1 CPU_MAX_CYC=4294967295"));
        assert(strstr(text,"MATH_MAX_US=4294967295"));
        assert(strlen(text)+13U<256U); break; /* Tagged response also fits. */
#endif
#if defined(FOC_PAIR_FAST_PATH)
    case 32: ready();
        cl_frame_cost=(FocFrameCost){.seq=123U,.pair_us=30U,.math_us=18U,.wall_cyc=10000U,.irq_cyc=4500U};
        ProtectedLoop_WorkEnd(t2.CNT-50U); off();
        assert(cl_late_cost.valid && cl_late_cost.seq==123U && cl_late_cost.elapsed_us==50U);
        assert(cl_late_cost.pair_us==30U && cl_late_cost.math_us==18U && cl_late_cost.irq_cyc==4500U);
        cl_frame_cost.seq=124U; ProtectedLoop_WorkEnd(t2.CNT-90U);
        assert(cl_late_cost.seq==123U && cl_late_cost.elapsed_us==50U);
        ProtectedLoop_Command("MOTOR TEST LATE",text,sizeof text);
        assert(strstr(text,"PATH=PAIR2 VALID=1 SEQ=123 US=50")); break;
    case 33: ready();
        cl_late_cost=(FocFrameCost){UINT32_MAX,UINT32_MAX,UINT32_MAX,UINT32_MAX,UINT32_MAX,UINT32_MAX,1U};
        memset(text,0xa5,sizeof text); ProtectedLoop_Command("MOTOR TEST LATE",text,sizeof text);
        assert(strstr(text,"IRQ_CYC=4294967295")); assert(strlen(text)+13U<256U); break;
#endif
#if defined(FOC_GUARD_FAST_PATH)
    case 34: ready(); encoder_theta_e_pred=NAN; tick(); off();
        assert(cl_flags&CL_BAD_ENCODER); break;
    case 35: run(); encoder_speed_rpm=nextafterf(60.0f,INFINITY); tick(); off();
        assert(cl_flags&CL_OVERSPEED); break;
    case 36: run(); encoder_speed_rpm=-60.0f; tick(); assert(!foc_fault);
        encoder_speed_rpm=-INFINITY; tick(); off(); assert(cl_flags&CL_OVERSPEED); break;
    case 37: ready(); encoder_theta_e_pred=INFINITY; tick(); off();
        assert(cl_flags&CL_BAD_ENCODER); break;
    case 38: run(); encoder_speed_rpm=NAN; tick(); off();
        assert(cl_flags&CL_OVERSPEED); break;
    case 39: ready(); gpio.ODR|=DRIVER_SD_Pin; tick(); off();
        assert(cl_flags&CL_BAD_OUTPUT); break;
    case 40: run(); cl_session.start_us=t2.CNT-400000U+25U;
        mock_sd_ignore_next_reset=1U; tick(); off();
        assert(cl_session.state==CL_FAULT &&
            cl_safety.protection.fault_flags&FOC_FB_OUTPUT_LOCK_LOST); break;
#endif
#if defined(FOC_GATE_REUSE)
    case 41: run(); cl_session.start_us=t2.CNT-400000U;
        t2.CNT+=50U; ++injected_seq_count;
        (void)ProtectedLoop_Pair(1551U,1551U); off();
        assert(cl_session.state==CL_DONE && !foc_fault); break;
    case 42: run(); cl_session.start_us=t2.CNT-400000U;
        t2.CNT+=50U; ++injected_seq_count;
        mock_sd_ignore_next_reset=1U; (void)ProtectedLoop_Pair(1551U,1551U); off();
        assert(foc_fault && cl_session.state==CL_FAULT); break;
    case 43: run(); break_on_time_call=2U; /* Break during pair transaction. */
        t2.CNT+=50U; ++injected_seq_count;
        (void)ProtectedLoop_Pair(1551U,1551U); off();
        assert(foc_fault && cl_session.state==CL_FAULT); break;
#endif
#if defined(FOC_IRQ_SOURCE_TRACE)
    case 44: {
        ready(); cl_frame_cost=(FocFrameCost){.seq=123U};
        cl_frame_irq=(FocIrqSourceFrame){.cycles={11U,22U,33U,44U},.calls={1U,2U,3U,4U}};
        ProtectedLoop_WorkEnd(t2.CNT-50U); off();
        cl_frame_irq.cycles[0]=999U; ProtectedLoop_WorkEnd(t2.CNT-90U);
        char irq_text[192]; ProtectedLoop_Command("MOTOR TEST IRQ",irq_text,sizeof irq_text);
        assert(strstr(irq_text,"VALID=1 SEQ=123 ERR=0 CYC=11,22,33,44 CNT=1,2,3,4"));
        for (unsigned i=0U;i<4U;++i) {
            cl_late_irq.cycles[i]=cl_late_irq.calls[i]=UINT32_MAX;
            source_load.stats.cycles[i]=source_load.stats.calls[i]=source_load.stats.max_inclusive[i]=UINT32_MAX;
        }
        cl_late_cost.seq=cl_late_irq.error=source_load.stats.error=UINT32_MAX;
        const char *irq_commands[]={"MOTOR TEST IRQ","MOTOR TEST IRQ STATS","MOTOR TEST IRQ TOTAL"};
        for (unsigned i=0U;i<3U;++i) {
            ProtectedLoop_Command(irq_commands[i],irq_text,sizeof irq_text);
            assert(strstr(irq_text,"4294967295") && strlen(irq_text)+13U<sizeof irq_text);
        }
        break;
    }
#endif
    default: assert(0);
    }
#if defined(FOC_FAST_MATH)
    assert(load.depth==0U);
#endif
    puts("PASS actual protected motor binding (register mocks, not hardware)"); return 0;
}
