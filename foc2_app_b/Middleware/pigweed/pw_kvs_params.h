#ifndef PW_KVS_PARAMS_H
#define PW_KVS_PARAMS_H

#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

enum
{
    PW_KVS_RESULT_OK = 0,
    PW_KVS_RESULT_NOT_FOUND = 1,
    PW_KVS_RESULT_ERROR = 2
};

typedef struct
{
    uint32_t initialized;
    uint32_t entries;
    uint32_t transaction_count;
    uint32_t writable_bytes;
    uint32_t in_use_bytes;
    uint32_t reclaimable_bytes;
    uint32_t sector_erase_count;
    uint32_t redundancy;
} PW_KvsDiagnostics_t;

int PW_Kvs_Init(void);
int PW_Kvs_LoadParams(void *record, size_t record_size);
int PW_Kvs_SaveParams(const void *record, size_t record_size);
void PW_Kvs_GetDiagnostics(PW_KvsDiagnostics_t *diagnostics);

#ifdef __cplusplus
}
#endif

#endif /* PW_KVS_PARAMS_H */
