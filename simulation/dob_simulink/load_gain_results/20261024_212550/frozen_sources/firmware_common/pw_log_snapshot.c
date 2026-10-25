#include "pw_log_snapshot.h"
#include <string.h>

int PW_LogSnapshot_Acquire(PW_LogSnapshot *snapshot) {
    if (snapshot == NULL || snapshot->refs != NULL || snapshot->count != 0U)
        return 0;
    PwLogRef pinned[16];
    const size_t count = PW_Log_HistorySnapshot(pinned, 16U);
#if defined(PW_ALLOCATOR_HYBRID)
    if (count != 0U &&
        !PW_Buffer_Allocate(count * sizeof(PwLogRef), PW_BUFFER_LOG_SNAPSHOT, &snapshot->index)) {
        for (size_t i = 0; i < count; ++i)
            (void)PwLogStore_Release(pinned[i]);
        return 0;
    }
    snapshot->refs = (PwLogRef *)snapshot->index.data;
#else
    snapshot->refs = snapshot->fixed;
#endif
    snapshot->count = count;
    if (count != 0U)
        memcpy(snapshot->refs, pinned, count * sizeof(PwLogRef));
    return 1;
}

void PW_LogSnapshot_Release(PW_LogSnapshot *snapshot) {
    if (snapshot == NULL)
        return;
    for (size_t i = 0; i < snapshot->count; ++i)
        (void)PwLogStore_Release(snapshot->refs[i]);
#if defined(PW_ALLOCATOR_HYBRID)
    if (snapshot->index.data != NULL)
        (void)PW_Buffer_Cancel(&snapshot->index);
#endif
    snapshot->count = 0U;
    snapshot->refs = NULL;
}
