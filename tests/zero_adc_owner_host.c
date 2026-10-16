/* Actual owner implementation under a bounded queue/task/HAL model.
 * No board IO. This checks ownership and admission, not electrical quality. */
#include <assert.h>
#include <stdarg.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "../firmware_common/foc_current_zero.h"

typedef enum { HAL_OK, HAL_ERROR, HAL_BUSY, HAL_TIMEOUT } HAL_StatusTypeDef;
typedef enum { PROTO_ERR_BUSY = 101, PROTO_ERR_NOT_READY = 104 } ProtocolError_t;
typedef void *TaskHandle_t;
typedef struct { uint8_t *storage; size_t size; unsigned full; } StaticQueue_t;
typedef StaticQueue_t *QueueHandle_t;
#define pdPASS 1
#define portMAX_DELAY UINT32_MAX
#define TIM_CR1_CEN 1U
static struct { uint32_t CR1; } tim1;
#define TIM1 (&tim1)
#define ADC_FULL_SCALE 4095U
#define ANALOG_VBUS_DIVIDER 25U

static TaskHandle_t current_task;
static const uintptr_t OWNER_TASK = 1U, PROTOCOL_TASK = 2U;
static struct { uint8_t active; } fw_update;
static FocZeroCal zero_retest_cal;
static uint8_t zero_retest_running, zero_retest_attempted, zero_retest_interlock_fault;
static uint8_t zero_retest_adc_ready = 1U, adc_fault;
static uint32_t zero_retest_started_ms, injected_seq_count;
static uint16_t analog_live_pc4_raw, analog_live_pc5_raw, analog_vdda_boot_mv = 3280U;
static uint8_t analog_vdda_boot_valid = 1U;
static unsigned trial, locked = 1U, clock_ok = 1U, dma_busy, parallel_ready = 1U;
static unsigned live_calls, dma_calls, zero_replies, dma_replies;
static unsigned fail_reply_send, corrupt_reply, mutate_after_reply;
#if defined(ADC_DMA_RAW_DIAGNOSTIC)
static unsigned dma_attempted, fail_start;
#endif
static unsigned fatal_calls, stop_calls, lose_during_sample;
static uint16_t input_pc4 = 590U, input_pc5 = 1288U;
static uint32_t tick = 1000U, primask;
static HAL_StatusTypeDef live_rc = HAL_OK;
static char output[400];

static void ZeroAdcOwner_Service(void);
static TaskHandle_t xTaskGetCurrentTaskHandle(void) { return current_task; }
static uint32_t HAL_GetTick(void) { return tick; }
static uint32_t __get_PRIMASK(void) { return primask; }
static void __disable_irq(void) { primask = 1U; }
static void __set_PRIMASK(uint32_t mask) { primask = mask; }
static uint8_t BootHealth_IsCurrentTrial(void) { return (uint8_t)trial; }
static uint8_t ZeroRetest_Locked(void) { return (uint8_t)locked; }
static uint8_t FocAdcClock_IsExpected(void) { return (uint8_t)clock_ok; }
static void Error_Handler(void) { ++fatal_calls; }
static void ZeroRetest_Stop(void)
{ ++stop_calls; TIM1->CR1 = 0U; zero_retest_running = 0U; }
static void ZeroRetest_Format(uint32_t id)
{ assert(current_task == (void *)PROTOCOL_TASK); ++zero_replies; (void)id; }
#if defined(ADC_DMA_RAW_DIAGNOSTIC)
static void ZeroRetest_DmaFormat(uint32_t id)
{ assert(current_task == (void *)PROTOCOL_TASK); ++dma_replies; (void)id; }
static int AdcDmaDiag_Busy(void) { return (int)dma_busy; }
static int AdcDmaDiag_Start(uint32_t now)
{
    assert(current_task == (void *)OWNER_TASK && locked && !adc_fault && clock_ok);
    assert(now == tick && primask == 0U);
    ++dma_calls;
    if (dma_attempted || fail_start) return 0;
    dma_attempted = dma_busy = 1U;
    TIM1->CR1 |= TIM_CR1_CEN;
    return 1;
}
#endif
#if defined(ADC_DMA_PARALLEL_DIAGNOSTIC)
static int AdcDmaDiag_ParallelReady(void) { return (int)parallel_ready; }
#endif
static HAL_StatusTypeDef ADC_AnalogLiveSample(void)
{
    assert(current_task == (void *)OWNER_TASK && primask == 0U);
    ++live_calls;
    if (live_rc == HAL_OK) {
        analog_live_pc4_raw = input_pc4;
        analog_live_pc5_raw = input_pc5;
    }
    tick += 2U;
    if (lose_during_sample == 1U) adc_fault = 1U;
    if (lose_during_sample == 2U) locked = 0U;
    if (lose_during_sample == 3U) clock_ok = 0U;
    return live_rc;
}
static QueueHandle_t xQueueCreateStatic(unsigned length, size_t size,
                                       uint8_t *storage, StaticQueue_t *queue)
{
    assert(length == 1U && current_task == (void *)OWNER_TASK);
    queue->storage = storage; queue->size = size; queue->full = 0U;
    return queue;
}
static int xQueueSend(QueueHandle_t queue, const void *data, uint32_t wait)
{
    assert(wait == 0U);
    if (queue->full) return 0;
    if (current_task == (void *)OWNER_TASK && fail_reply_send) return 0;
    memcpy(queue->storage, data, queue->size); queue->full = 1U;
    if (current_task == (void *)OWNER_TASK && corrupt_reply) queue->storage[0] ^= 1U;
    return pdPASS;
}
static int xQueueReceive(QueueHandle_t queue, void *data, uint32_t wait)
{
    if (!queue->full && wait == portMAX_DELAY) {
        assert(current_task == (void *)PROTOCOL_TASK);
        current_task = (void *)OWNER_TASK;
        ZeroAdcOwner_Service();
        if (mutate_after_reply) analog_live_pc4_raw = 0U;
        current_task = (void *)PROTOCOL_TASK;
    }
    if (!queue->full) return 0;
    memcpy(data, queue->storage, queue->size); queue->full = 0U;
    return pdPASS;
}
static uint8_t Protocol_SendFormatted(char *buffer, size_t capacity,
                                      const char *format, ...)
{
    assert(current_task == (void *)PROTOCOL_TASK);
    va_list args; va_start(args, format);
    int count = vsnprintf(buffer, capacity, format, args); va_end(args);
    assert(count >= 0 && (size_t)count < capacity && capacity <= sizeof(output));
    memcpy(output, buffer, (size_t)count + 1U);
    return 1U;
}
static void Protocol_SendError(uint32_t id, ProtocolError_t code, const char *name)
{
    (void)id; (void)code;
    (void)snprintf(output, sizeof(output), "%s", name);
}
#include "../firmware_common/zero_adc_owner.inc"

static void check_not_started(void)
{
    assert(!dma_calls && !zero_replies && !dma_replies && !zero_retest_attempted);
}
int main(int argc, char **argv)
{
    assert(argc == 2);
    unsigned scenario = (unsigned)strtoul(argv[1], NULL, 10);
    current_task = (void *)OWNER_TASK; ZeroAdcOwner_Init();
    current_task = (void *)PROTOCOL_TASK;
#if defined(ADC_DMA_RAW_DIAGNOSTIC)
    uint8_t kind = ZERO_ADC_ACQUIRE_DMA;
#else
    uint8_t kind = ZERO_ADC_ACQUIRE_ZERO;
#endif
    switch (scenario) {
    case 0: break;
    case 1:
        assert(ZeroAdcOwner_LiveSample() == HAL_ERROR); assert(!live_calls); break;
    case 2: trial = 1U; break;
    case 3: fw_update.active = 1U; break;
    case 4: locked = 0U; break;
    case 5: zero_retest_adc_ready = 0U; break;
    case 6: adc_fault = 1U; break;
    case 7: clock_ok = 0U; break;
    case 8: dma_busy = 1U; zero_retest_running = 1U; break;
    case 9: TIM1->CR1 = TIM_CR1_CEN; break;
    case 10: parallel_ready = 0U; clock_ok = 0U; break;
    case 11: live_rc = HAL_TIMEOUT; break;
    case 12: live_rc = HAL_ERROR; break;
    case 13: analog_vdda_boot_valid = 0U; break;
    case 14: analog_vdda_boot_mv = 0U; break;
    case 15: input_pc4 = 499U; break;
    case 16: input_pc4 = 700U; break;
    case 17: input_pc4 = 500U; break;
    case 18: input_pc4 = 699U; break;
    case 19: input_pc4 = 4096U; break;
    case 20: kind = 99U; break;
    case 21:
        current_task = (void *)OWNER_TASK;
        ZeroRetest_SubmitAcquisition(777U, kind);
        assert(strstr(output, "OWNER_UNAVAILABLE")); assert(!live_calls); return 0;
    case 22: zero_adc_requests = NULL; break;
    case 23:
        ZeroAdcOwner_Service(); assert(!live_calls); break;
    case 24: input_pc4 = 1288U; mutate_after_reply = 1U; break;
    case 25:
        current_task = (void *)OWNER_TASK;
        assert(ZeroAdcOwner_LiveSample() == HAL_OK);
        assert(live_calls == 1U && analog_live_pc4_raw == 590U);
        current_task = (void *)PROTOCOL_TASK; live_calls = 0U; break;
    case 26: fail_reply_send = 1U; break;
    case 27: corrupt_reply = 1U; break;
    case 28: lose_during_sample = 1U; break;
    case 29: lose_during_sample = 2U; break;
    case 30: lose_during_sample = 3U; break;
    case 31: live_rc = HAL_BUSY; break;
    case 32: zero_retest_interlock_fault = 1U; break;
    case 33:
        current_task = (void *)OWNER_TASK; TIM1->CR1 = TIM_CR1_CEN;
        assert(ZeroAdcOwner_LiveSample() == HAL_BUSY); assert(!live_calls); return 0;
    case 34:
        current_task = (void *)OWNER_TASK; zero_retest_running = 1U;
        assert(ZeroAdcOwner_LiveSample() == HAL_BUSY); assert(!live_calls); return 0;
    case 35: input_pc5 = 4096U; break;
    case 36:
#if defined(ADC_DMA_RAW_DIAGNOSTIC)
        kind = ZERO_ADC_ACQUIRE_ZERO;
#else
        kind = ZERO_ADC_ACQUIRE_DMA;
#endif
        break;
    case 37:
#if defined(ADC_DMA_RAW_DIAGNOSTIC)
        fail_start = 1U;
#else
        zero_retest_attempted = 1U;
#endif
        break;
    case 38: {
        ZeroAdcRequest occupied = {123U, kind};
        assert(xQueueSend(zero_adc_requests, &occupied, 0U) == pdPASS);
        ZeroRetest_SubmitAcquisition(777U, kind);
        assert(strstr(output, "OWNER_UNAVAILABLE") && !live_calls);
        return 0;
    }
    case 39:
#if defined(ADC_DMA_PARALLEL_DIAGNOSTIC)
        parallel_ready = 0U;
#else
        clock_ok = 0U;
#endif
        break;
    case 40:
        current_task = (void *)OWNER_TASK;
#if defined(ADC_DMA_RAW_DIAGNOSTIC)
        dma_busy = 1U;
#else
        zero_retest_running = 1U;
#endif
        assert(ZeroAdcOwner_LiveSample() == HAL_BUSY && !live_calls);
        return 0;
    case 41: kind = ZERO_ADC_ACQUIRE_REFERENCE_OFF; break;
    case 42: kind = ZERO_ADC_ACQUIRE_REFERENCE_ON; break;
    default: assert(0);
    }
    ZeroRetest_SubmitAcquisition(777U, kind);
    if (scenario == 0U || scenario == 1U || scenario == 17U || scenario == 18U ||
        scenario == 23U || scenario == 25U
#if defined(ADC_DMA_RAW_DIAGNOSTIC) && !defined(ADC_DMA_THREE_PHASE_DIAGNOSTIC)
        || scenario == 36U
#endif
        ) {
        assert(live_calls == 1U && !output[0] && !fatal_calls);
#if defined(ADC_DMA_RAW_DIAGNOSTIC)
        if (kind == ZERO_ADC_ACQUIRE_DMA) {
            assert(dma_calls == 1U && dma_replies == 1U && !zero_replies);
        } else {
            assert(zero_replies == 1U && zero_retest_attempted && zero_retest_running);
        }
#else
        assert(zero_replies == 1U && zero_retest_attempted && zero_retest_running);
        assert(zero_retest_started_ms == tick);
#endif
        /* A second request while acquisition is active cannot touch ADC2. */
        unsigned before = live_calls;
        ZeroRetest_SubmitAcquisition(778U, kind);
        assert(live_calls == before && strstr(output, "NOT_ADMITTED"));
    } else if (scenario == 37U) {
#if defined(ADC_DMA_RAW_DIAGNOSTIC)
        assert(dma_calls == 1U && !dma_attempted && !dma_replies);
        assert(strstr(output, "ONESHOT_OR_CONFIG") && !(TIM1->CR1 & TIM_CR1_CEN));
#else
        assert(!live_calls && strstr(output, "NOT_ADMITTED"));
#endif
    } else if (scenario == 26U || scenario == 27U) {
        assert(strstr(output, "REPLY_MISMATCH"));
        if (scenario == 26U) {
            assert(fatal_calls == 1U && stop_calls == 1U && !(TIM1->CR1 & TIM_CR1_CEN));
        }
    } else {
        check_not_started(); assert(output[0]);
        if ((scenario >= 2U && scenario <= 10U) || scenario == 20U ||
            scenario == 22U || scenario == 32U || scenario == 36U || scenario == 39U ||
            scenario == 41U || scenario == 42U) {
            assert(!live_calls);
        }
        if (scenario == 15U || scenario == 16U || scenario == 24U) {
            assert(strstr(output, "REQUIRES_12V_ANALOG_SUPPLY"));
            assert(strstr(output, "SUPPLY_VALID=1"));
        }
        if (scenario == 24U) {
            assert(strstr(output, "PC4_RAW=1288") && strstr(output, "VBUS_EST_MV=25791"));
            assert(analog_live_pc4_raw == 0U); /* Reply did not reread shared state. */
        }
        if (scenario == 11U || scenario == 12U || scenario == 31U)
            assert(strstr(output, "SUPPLY_VALID=0") && strstr(output, "PC4_RAW=0"));
    }
    assert(!primask); /* HAL polling never occurred with interrupts masked. */
    printf("OWNER scenario %u PASS\n", scenario);
    return 0;
}
