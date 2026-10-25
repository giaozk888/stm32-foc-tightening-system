#include "pw_can_log.h"
#include "main.h"
#include "can_log_v1.h"
#include "can_status_tx.h"
#include "pw_log_backend.h"
#include "FreeRTOS.h"
#include "queue.h"
#include "task.h"

#define DEPTH 8U
typedef struct { uint32_t created_ms; PwLogRef ref; uint16_t length; } Record;
static StaticQueue_t queue_control;
static uint8_t queue_storage[DEPTH * sizeof(Record)];
static QueueHandle_t queue;
static Record current;
static uint8_t pending, first_session = 1U, fragment_index, header_sent;
static uint16_t next_id, current_id;
static uint32_t dropped_queue, dropped_stale, records_enqueued;
static uint32_t last_service_ms, last_stats_ms;
static uint8_t serviced;

static uint8_t capture(PwLogRef ref)
{
    const PwLogRecord *view = PwLogStore_View(ref);
    const char *text = view != NULL ? view->text : NULL;
    size_t length = view != NULL ? view->length : 0U;
    if (!queue || !text || __get_IPSR() != 0U) return 0U;
    while (length && (text[length - 1U] == '\r' || text[length - 1U] == '\n')) --length;
    if (!length || length > CAN_LOG_MAX_TEXT) return 0U;
    Record record;
    record.created_ms = HAL_GetTick();
    if (!PwLogStore_Retain(ref)) return 0U;
    record.ref = ref;
    record.length = (uint16_t)length;
    if (xQueueSend(queue, &record, 0U) != pdPASS) {
        (void)PwLogStore_Release(ref);
        taskENTER_CRITICAL(); ++dropped_queue; taskEXIT_CRITICAL();
        return 0U;
    }
    return 1U;
}
uint8_t PW_CanLog_Init(void)
{
    if (queue) return 1U;
    queue = xQueueCreateStatic(DEPTH, sizeof(Record), queue_storage, &queue_control);
    if (!queue) return 0U;
    PW_Log_SetSharedCanMirrorCallback(capture);
    return 1U;
}
static void u16(uint8_t *out, uint32_t value)
{
    if (value > 65535U) value = 65535U;
    out[0] = (uint8_t)value; out[1] = (uint8_t)(value >> 8);
}
void PW_CanLog_Service(uint32_t now_ms)
{
    if (!queue || (serviced && (uint32_t)(now_ms - last_service_ms) < 100U)) return;
    serviced = 1U; last_service_ms = now_ms;
    /* Two frames per 100 ms at most, including diagnostics. No wait/retry loop.
       A full HAL FIFO is not a reason to block or change motor control. */
    for (unsigned budget = 0; budget < 2U; ++budget) {
        uint8_t frame[8];
        if ((uint32_t)(now_ms - last_stats_ms) >= 1000U) {
            uint32_t dropped;
            taskENTER_CRITICAL(); dropped = dropped_queue; taskEXIT_CRITICAL();
            frame[0] = 1U; frame[1] = (uint8_t)uxQueueMessagesWaiting(queue);
            u16(frame + 2, dropped); u16(frame + 4, dropped_stale); u16(frame + 6, records_enqueued);
            if (!CAN_StatusTx_TryLogFrame(CAN_LOG_STATS_ID, frame)) return;
            last_stats_ms = now_ms;
            continue;
        }
        if (!pending) {
            if (xQueueReceive(queue, &current, 0U) != pdTRUE) return;
            current_id = next_id++;
            fragment_index = 0U; header_sent = 0U; pending = 1U;
        }
        if ((uint32_t)(now_ms - current.created_ms) > 10000U) {
            (void)PwLogStore_Release(current.ref);
            pending = 0U; ++dropped_stale;
            continue;
        }
        uint32_t id = header_sent ? CAN_LOG_DATA_ID : CAN_LOG_START_ID;
        const PwLogRecord *view = PwLogStore_View(current.ref);
        if (view == NULL) {
            (void)PwLogStore_Release(current.ref); pending = 0U; ++dropped_stale; continue;
        }
        if (!header_sent) {
            (void)CanLog_EncodeStart(current_id, first_session ? CAN_LOG_FLAG_SESSION_START : 0U,
                                    (const uint8_t *)view->text, current.length, frame);
        } else {
            (void)CanLog_EncodeData(current_id, fragment_index,
                                    (const uint8_t *)view->text, current.length, frame);
        }
        if (!CAN_StatusTx_TryLogFrame(id, frame)) return;
        if (!header_sent) header_sent = 1U;
        else if ((uint16_t)(++fragment_index * CAN_LOG_CHUNK_SIZE) >= current.length) {
            (void)PwLogStore_Release(current.ref);
            pending = 0U; first_session = 0U; ++records_enqueued;
        }
    }
}
