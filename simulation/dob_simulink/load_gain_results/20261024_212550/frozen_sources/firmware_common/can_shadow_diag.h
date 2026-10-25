#ifndef CAN_SHADOW_DIAG_H
#define CAN_SHADOW_DIAG_H

#include <stdint.h>

/* Diagnostic-only CAN exchange. These IDs are not motor-control commands. */
#define CAN_SHADOW_REQUEST_ID 0x220U
#define CAN_SHADOW_REPLY_ID 0x2A0U
#define CAN_SHADOW_VERSION 1U
#define CAN_SHADOW_WINDOW_MS 500U
#define CAN_SHADOW_MAX_TEST_VALUE 1000U

typedef enum {
    CAN_SHADOW_PROBE = 1,
    CAN_SHADOW_CHECK_VALUE = 2,
    CAN_SHADOW_STOP_TEST = 3
} CanShadow_Opcode;

typedef enum {
    CAN_SHADOW_PROBE_READY = 1,
    CAN_SHADOW_VALUE_OK_NO_ACTION = 2,
    CAN_SHADOW_STOP_OBSERVED_NO_ACTION = 3,
    CAN_SHADOW_REJECT_RANGE = 4,
    CAN_SHADOW_REJECT_SEQUENCE = 5,
    CAN_SHADOW_REJECT_TIMEOUT = 6,
    CAN_SHADOW_REJECT_NO_PROBE = 7,
    CAN_SHADOW_REJECT_OPCODE = 8,
    CAN_SHADOW_REJECT_VALUE = 9
} CanShadow_Decision;

typedef struct {
    uint8_t opcode;
    uint16_t sequence;
    uint16_t test_value;
} CanShadow_Request;

typedef struct {
    uint16_t last_sequence;
    uint32_t opened_at_ms;
    uint8_t sequence_seen;
    uint8_t probe_open;
    uint8_t probe_expired;
} CanShadow_State;

/* Exact standard, classic data frame, DLC=8; bad frames are silently dropped. */
uint8_t CanShadow_DecodeRequest(uint32_t id, uint8_t extended,
                                uint8_t remote, uint8_t fd_format,
                                uint8_t dlc, const uint8_t *data,
                                CanShadow_Request *out);
uint8_t CanShadow_EncodeRequest(const CanShadow_Request *request,
                                uint8_t out[8]);
uint8_t CanShadow_EncodeReply(const CanShadow_Request *request,
                              CanShadow_Decision decision, uint8_t out[8]);
void CanShadow_Reset(CanShadow_State *state);
/* Returns 1 exactly once when a pending probe expires. */
uint8_t CanShadow_Tick(CanShadow_State *state, uint32_t now_ms);
/* Pure diagnostic state machine; cannot call any motor or HAL function. */
CanShadow_Decision CanShadow_Evaluate(CanShadow_State *state,
                                      const CanShadow_Request *request,
                                      uint32_t now_ms);

#endif
