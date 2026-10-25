#ifndef TIGHTEN_PARAMS_STORAGE_H
#define TIGHTEN_PARAMS_STORAGE_H

#include "tighten_params.h"

typedef struct {
    TightenParams_t params;
    volatile uint8_t flash_valid;
    volatile uint8_t dirty;
    volatile uint32_t last_crc32;
    volatile uint8_t kvs_ready;
    volatile uint8_t kvs_migrated;
} TightenParamsState_t;

#define TIGHTEN_PARAMS_STATE_INITIALIZER \
    { TIGHTEN_PARAMS_DEFAULT_INITIALIZER, 0U, 0U, 0U, 0U, 0U }

typedef enum {
    PARAM_FLASH_LOAD_OK = 0,
    PARAM_FLASH_LOAD_EMPTY,
    PARAM_FLASH_LOAD_INVALID,
    PARAM_FLASH_LOAD_HAL_ERROR
} TightenParamsFlashLoadStatus_t;

/* Port results follow PW_KVS_RESULT_OK=0, NOT_FOUND=1, ERROR=2.
 * Callbacks are synchronous and must copy exactly length bytes on success.
 * Storage does not acquire a task lock or enforce motion/upgrade gates;
 * the application must keep its existing command-level guards.
 */
typedef struct {
    void *context;
    int (*load)(void *context, void *data, size_t length);
    int (*save)(void *context, const void *data, size_t length);
    void (*read_legacy)(void *context, void *data, size_t length);
} TightenParamsStoragePort_t;

#ifdef __cplusplus
extern "C" {
#endif
TightenParamsFlashLoadStatus_t TightenParams_StorageLoad(
    TightenParamsState_t *state, const TightenParamsStoragePort_t *port);
uint8_t TightenParams_StorageSave(
    TightenParamsState_t *state, const TightenParamsStoragePort_t *port);
/* send must consume/copy the string before returning; buffer is stack-owned.
 * Return value is deliberately ignored, matching the existing PARAMS output.
 */
void TightenParams_EmitAll(const TightenParamsState_t *state,
                          uint32_t request_id, uint8_t (*send)(const char *));
/* New producers pass formatting arguments before any stack string is built.
 * The callback may generate in its own DMA lease; fallback is valid only for
 * synchronous formatting/consumption. The 20-line wire contract is unchanged. */
typedef uint8_t (*TightenParamsFormatSendFn)(char *fallback, size_t capacity,
                                            const char *format, ...);
void TightenParams_EmitAllFormatted(const TightenParamsState_t *state,
                                  uint32_t request_id,
                                  TightenParamsFormatSendFn send);
#ifdef __cplusplus
}
#endif
#endif
