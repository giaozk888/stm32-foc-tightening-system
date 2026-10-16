#include "pw_log_backend.h"
#include "as5047p_dma_stm32.h"
#include "FreeRTOS.h"
#include <assert.h>
#include <string.h>
#include "../can_rpc_host/test_assert.h"
static PwLogRef history[16];
static size_t count;
void TransferTest_ClearHistory(void) {
    for (size_t i = 0; i < count; ++i)
        assert(PwLogStore_Release(history[i]));
    count = 0;
}
void TransferTest_SetHistory(const char *data, size_t length) {
    TransferTest_ClearHistory();
    while (length) {
        PwLogLease lease = {0};
        assert(count < 16 && PwLogStore_Acquire(&lease));
        size_t size = length < 191 ? length : 191;
        memcpy(lease.record->text, data, size);
        lease.record->text[size] = '\0';
        lease.record->length = (uint16_t)size;
        assert(PwLogStore_Seal(&lease, &history[count++]));
        data += size;
        length -= size;
    }
}
size_t PW_Log_HistorySnapshot(PwLogRef *out, size_t capacity) {
    taskENTER_CRITICAL();
    size_t size = count < capacity ? count : capacity;
    for (size_t i = 0; i < size; ++i) {
        assert(PwLogStore_Retain(history[i]));
        out[i] = history[i];
    }
    taskEXIT_CRITICAL();
    return size;
}
void PW_Log_GetDiagnostics(PW_LogDiagnostics_t *out) {
    memset(out, 0, sizeof(*out));
    out->ready = 1;
}
int AS5047P_DmaGetSample(AsDmaSample *out) {
    *out = (AsDmaSample){.sequence = 9,
                         .sample_us = 100,
                         .completed_us = 130,
                         .elapsed_us = 30,
                         .status = AS_DMA_OK,
                         .raw = 1234,
                         .response = 1234};
    return 1;
}
uint32_t AS5047P_DmaNowUs(void) {
    return 150;
}
int AS5047P_DmaSnapshot(AsDmaSample *out, uint32_t *now) {
    *now = AS5047P_DmaNowUs();
    return AS5047P_DmaGetSample(out);
}
