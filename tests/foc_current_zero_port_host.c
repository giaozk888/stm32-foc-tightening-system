/* Exercise the actual STM32 binding with mock registers. No hardware access. */
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#undef assert
/* Host assertion failure must not open a blocking Windows CRT dialog. */
#define assert(x) do { if (!(x)) { fprintf(stderr,"CHECK line %d: %s\n",__LINE__,#x); exit(1); } } while (0)
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include "foc_current_zero.h"
#include "foc_current_median.h"
#if defined(FOC_CURRENT_TREND4)
#include "foc_overcurrent_shadow.h"
static FocOcShadow foc_oc_shadow;
static uint32_t foc_trend_pairs, foc_trend_changed, foc_trend_u_changed, foc_trend_v_changed;
#endif

typedef void *TaskHandle_t;
typedef uint32_t StackType_t;
typedef struct { uint32_t CR1, CCER, BDTR, DIER; } MockTim;
typedef struct { uint32_t ODR, BSRR; } MockGpio;
static MockTim timer;
static MockGpio gpio;
#define TIM1 (&timer)
#define DRIVER_SD_GPIO_Port (&gpio)
#define DRIVER_SD_Pin 64U
#define TIM_CR1_CEN 1U
#define TIM_BDTR_MOE 32768U
#define TIM_BDTR_AOE 16384U
#define TIM_DIER_UIE 1U
#define TIM_DIER_CC4IE 16U
#define ADC_FULL_SCALE 4095U
#define FOC_FAULT_STARTUP_ZERO_CAL 7U
#define FOC_WINDOW_OK 0U
#define MOTOR_MODE_IDLE 0U
#define pdMS_TO_TICKS(ms) (ms)
static uint32_t primask, tick, delay_mode, dma_stops, in_isr;
static uint8_t periodic, planner_ok = 1U, analog_safe_latched, foc_enable;
static uint8_t adc_fault, foc_fault, foc_fault_reason, encoder_valid;
static uint8_t run_zero_cal_done, current_filter_enable, current_prev_raw_valid;
static uint8_t encoder_prev_valid, current_med_index, current_med_count;
static uint8_t analog_vdda_boot_valid;
static uint16_t analog_vdda_boot_mv;
static uint16_t iu_zero_raw, iv_zero_raw, iw_zero_raw;
static uint16_t iu_inj_raw, iv_inj_raw, iw_inj_raw;
static uint16_t current_prev_raw_u, current_prev_raw_v;
static uint16_t current_med_u[3], current_med_v[3];
#if defined(FOC_CURRENT_SPIKE_ONLY)
static FocCurrentMedian current_spike_filter;
#endif
static uint32_t injected_seq_count, foc_control_count, current_valid_count;
static uint32_t current_reject_count, current_reject_streak;
static uint32_t run_zero_valid_count, run_zero_reject_count;
static uint32_t motor_control_mode, tightening_start_request;
static int32_t current_last_rejected_sum_counts;
static float foc_id_ref_A, foc_iq_ref_A, encoder_theta_e_pred, encoder_theta_e;
static float encoder_speed_dt_accum_s;
static struct { uint8_t valid; } encoder_dma_cursor;
static struct { uint8_t active; } fw_update;
static TaskHandle_t motor_control_task_handle;
static char last_uart[256];
#if defined(FOC_CURRENT_SPIKE_ONLY)
#define FILTER_WARMUP_PAIRS (FOC_CURRENT_HISTORY_PAIRS - 1U)
#else
#define FILTER_WARMUP_PAIRS 0U
#endif

static uint32_t __get_PRIMASK(void) { return primask; }
static void __disable_irq(void) { primask = 1U; }
static void __set_PRIMASK(uint32_t value) { primask = value; }
static void __DMB(void) { }
static uint32_t HAL_GetTick(void) { return tick; }
static int AS5047P_DmaIsPeriodic(void) { return periodic; }
static void AS5047P_DmaStopPeriodic(void)
{ assert(in_isr == 0U); periodic = 0U; ++dma_stops; }
static int AS5047P_DmaStartPeriodic(void) { periodic = 1U; return 1; }
static void FOC_ResetController(void) { }
static void MotorControl_SetIdle(void) { motor_control_mode = MOTOR_MODE_IDLE; }
static int Tightening_IsBusy(void) { return 0; }
static uint32_t FocAdcTiming_Commit(float u, float v, float w)
{ (void)u; (void)v; (void)w; return planner_ok ? 0U : 1U; }
static int FocAdcTiming_CanStart(void) { return planner_ok; }
static void EncoderDma_FaultFromISR(void) { foc_fault = 1U; }
static int FOC_EncoderSpeedUpdate(float dt) { (void)dt; return 1; }
static uint32_t uxTaskGetStackHighWaterMark(TaskHandle_t task)
{ (void)task; return 128U; }
static uint32_t PW_RouterTransfer_StackFreeBytes(void) { return 512U; }
static uint32_t xPortGetFreeHeapSize(void) { return 4096U; }
static uint32_t xPortGetMinimumEverFreeHeapSize(void) { return 2048U; }
static void UART_SendLiteral(const char *message)
{ assert(!in_isr && !primask); snprintf(last_uart, sizeof(last_uart), "%s", message); }
static void vTaskDelay(uint32_t ms);
#include "isolated_concurrency.inc"

static int Feed(uint16_t u, uint16_t v)
{
    in_isr = 1U;
    ++injected_seq_count;
    int consumed = IsolatedZero_Feed(u, v);
    in_isr = 0U;
    return consumed;
}
static void vTaskDelay(uint32_t ms)
{
    assert(!in_isr && !primask);
    for (uint32_t m = 0; m < ms; ++m) {
        ++tick;
        if (delay_mode && isolated_running && (TIM1->CR1 & TIM_CR1_CEN)) {
            for (uint32_t sample = 0; sample < 20U && isolated_running; ++sample) {
                uint16_t u = delay_mode == 2U ? 1853U : 1560U;
                (void)Feed(u, 1565U);
            }
        }
    }
}
static void Reset(void)
{
    memset(&isolated_zero, 0, sizeof(isolated_zero));
    memset(&timer, 0, sizeof(timer)); memset(&gpio, 0, sizeof(gpio));
    primask = tick = delay_mode = dma_stops = in_isr = 0U;
    periodic = isolated_running = isolated_zero_ready = isolated_zero_shutdown_pending = 0U;
    foc_fault = adc_fault = foc_enable = run_zero_cal_done = current_filter_enable = 0U;
    foc_fault_reason = 0U; encoder_valid = analog_safe_latched = planner_ok = 1U;
    analog_vdda_boot_valid = 1U; analog_vdda_boot_mv = 3281U;
    fw_update.active = 0U; motor_control_mode = MOTOR_MODE_IDLE;
    tightening_start_request = 0U;
    injected_seq_count = foc_control_count = 0U;
    iu_zero_raw = 1234U; iv_zero_raw = 1235U;
    last_uart[0] = '\0';
}
static void RequireOff(void)
{
    assert(IsolatedBench_Locked());
    assert(!(TIM1->BDTR & (TIM_BDTR_MOE | TIM_BDTR_AOE)) && !TIM1->CCER);
    assert(!foc_enable && !primask);
}
int main(void)
{
    FocZeroCal snap;
    char message[192];
    Reset(); assert(IsolatedBench_Start(30000U)); RequireOff();
    assert(!IsolatedBench_Active() && !run_zero_cal_done);
    for (uint32_t n = 0; n < FOC_ZERO_SETTLE_PAIRS + FOC_ZERO_WINDOW_PAIRS + FILTER_WARMUP_PAIRS - 1U; ++n)
        assert(Feed(1560U, 1565U));
    assert(iu_zero_raw == 1234U && !isolated_zero_ready && !current_filter_enable);
    assert(Feed(1560U, 1565U)); /* Completion pair still not a control command. */
    assert(IsolatedBench_Active() && iu_zero_raw == 1560U && iv_zero_raw == 1565U);
    assert(current_filter_enable && run_zero_cal_done && current_valid_count == 0U);
    assert(!Feed(1560U, 1565U));
    IsolatedZero_Snapshot(&snap); assert(snap.state == FOC_ZERO_READY && !primask);
    IsolatedZero_Format(message, sizeof(message));
    assert(strstr(message, "STATE=3 REASON=0") && strstr(message, "N=4000"));
    assert(strlen(message) < sizeof(message) - 1U && strstr(message, "LAST=1560,1565"));
    IsolatedBench_Service(); assert(periodic); RequireOff();
    IsolatedBench_Format(message, sizeof(message)); assert(strstr(message, "ZERO=1"));
    IsolatedBench_Stacks(message, sizeof(message)); assert(strstr(message, "HEAP=4096"));
    IsolatedBench_Stop(0U); assert(!isolated_running && !periodic && dma_stops == 1U);
    assert(!(TIM1->CR1 & TIM_CR1_CEN)); RequireOff();

    /* Reject an unsafe gate condition and defer DMA cleanup out of the ISR. */
    Reset(); assert(IsolatedBench_Start(30000U)); periodic = 1U;
    TIM1->BDTR |= TIM_BDTR_MOE; assert(Feed(1560U, 1565U));
    assert(foc_fault && foc_fault_reason == 7U && !isolated_zero_ready);
    assert(isolated_zero.reason == FOC_ZERO_UNSAFE && !dma_stops);
    assert(!TIM1->CCER && !(TIM1->CR1 & TIM_CR1_CEN)); RequireOff();
    IsolatedBench_Service(); assert(dma_stops == 1U && !isolated_zero_shutdown_pending);
    IsolatedZero_Fail(FOC_ZERO_TIMEOUT); assert(isolated_zero.reason == FOC_ZERO_UNSAFE);

    /* Real Wait integration: scheduler tick drives 20 raw pairs per ms. */
    Reset(); assert(IsolatedBench_Start(30000U)); delay_mode = 1U;
    IsolatedZero_Wait(); assert(isolated_zero_ready && tick == 1200U + (FILTER_WARMUP_PAIRS != 0U));
    assert(strstr(last_uart, "ISOLATED ZERO PASS")); RequireOff();
    Reset(); assert(IsolatedBench_Start(30000U)); delay_mode = 2U;
    IsolatedZero_Wait(); assert(isolated_zero.reason == FOC_ZERO_OUT_OF_RANGE);
    assert(strstr(last_uart, "ISOLATED ZERO FAIL") && foc_fault && !isolated_running);
    RequireOff();
    Reset(); tick = UINT32_MAX - 50U; assert(IsolatedBench_Start(30000U));
    IsolatedZero_Wait(); assert(isolated_zero.reason == FOC_ZERO_TIMEOUT);
    assert(!isolated_running && !isolated_zero_ready); RequireOff();

    Reset(); assert(IsolatedBench_Start(30000U)); IsolatedBench_Stop(0U);
    assert(isolated_zero.reason == FOC_ZERO_STOPPED && !run_zero_cal_done);
    Reset(); analog_vdda_boot_valid = 0U; assert(!IsolatedBench_Start(30000U));
    assert(isolated_zero.reason == FOC_ZERO_BAD_CONFIG); RequireOff();
    Reset(); planner_ok = 0U; assert(!IsolatedBench_Start(30000U)); RequireOff();
    Reset(); foc_fault = 1U; foc_fault_reason = 1U;
    assert(!IsolatedBench_Start(30000U)); IsolatedZero_Fail(FOC_ZERO_RATE);
    assert(foc_fault_reason == 1U); RequireOff();
#if defined(FOC_ZERO_MEDIAN_COMPUTE_ONLY)
    Reset(); assert(IsolatedBench_Start(30000U));
    for (uint32_t n = 0; n < FOC_ZERO_SETTLE_PAIRS + FOC_ZERO_WINDOW_PAIRS + FILTER_WARMUP_PAIRS; ++n) {
        uint16_t raw_u = n == FOC_ZERO_SETTLE_PAIRS + 100U ? 1750U : 1560U;
        assert(Feed(raw_u, 1565U));
        RequireOff();
    }
    assert(IsolatedBench_Active() && iu_zero_raw == 1560U);
    assert(isolated_zero_median.raw.state == FOC_ZERO_FAILED);
    assert(isolated_zero_median.raw.reason == FOC_ZERO_OUT_OF_RANGE);
    assert(isolated_zero_median.outside_nominal == 1U);
    assert(isolated_zero_median.raw.zero_u == 0U);
    char filter_message[320];
    IsolatedZero_FilterFormat(filter_message, sizeof(filter_message));
    assert(strstr(filter_message, "COMPUTE_ONLY=1 MOTOR_QUALIFIED=0"));
    assert(strstr(filter_message, "RAW_STATE=4 RAW_REASON=2"));
#if defined(FOC_CURRENT_SPIKE_ONLY)
    assert(strstr(filter_message, FOC_CURRENT_FILTER_FIELDS));
#if defined(FOC_CURRENT_TREND4)
    assert(strstr(filter_message, "PAIRS=24003 FILTER_STATE=3"));
#else
    assert(strstr(filter_message, "PAIRS=24002 FILTER_STATE=3"));
#endif
    assert(isolated_zero_median.raw_window_pairs == 4000U + FILTER_WARMUP_PAIRS);
#else
    assert(strstr(filter_message, "PAIRS=24000 FILTER_STATE=3"));
#endif
    assert(strlen(filter_message) < sizeof(filter_message) - 1U);
    /* Failure in the actual filtered pipeline still prevents publication. */
    Reset(); assert(IsolatedBench_Start(30000U));
    for (uint32_t n = 0; n < FOC_ZERO_SETTLE_PAIRS + 100U; ++n) assert(Feed(1560U,1565U));
    assert(Feed(1750U, 1565U)); assert(Feed(1750U, 1565U));
#if defined(FOC_CURRENT_SPIKE_ONLY)
    assert(Feed(1750U, 1565U)); /* Delayed original step is NOT filtered away. */
#endif
    assert(foc_fault && !isolated_zero_ready && iu_zero_raw == 1234U);
    RequireOff();
#endif
    puts("STABLE ZERO PORT PASS: real binding, READY publish, no early FOC, hard-off, deferred cleanup, first fault, timeout/wrap and diagnostics.");
    return 0;
}
