#ifndef CAN_CONTROL_V0_H
#define CAN_CONTROL_V0_H

#include <stdint.h>

/* Protocol contract. The optional on-device receiver is reject-only. */
#ifdef __cplusplus
extern "C" {
#endif
#define CAN_CONTROL_V0_REQUEST_ID 0x200U
#define CAN_CONTROL_V0_REPLY_ID 0x280U
#define CAN_CONTROL_V0_VERSION 1U
#define CAN_CONTROL_V0_ARM_WINDOW_MS 500U

typedef enum {
    CAN_CONTROL_V0_ARM = 1,
    CAN_CONTROL_V0_START = 2,
    CAN_CONTROL_V0_STOP = 3
} CanControlV0_Opcode;

typedef struct {
    uint8_t opcode;
    uint16_t sequence;
    uint16_t session_token;
    uint16_t recipe_id;
} CanControlV0_Request;

typedef enum {
    CAN_CONTROL_V0_INVALID = 0,
    CAN_CONTROL_V0_STOP_INTENT = 1,
    CAN_CONTROL_V0_ARMED = 2,
    CAN_CONTROL_V0_START_INTENT = 3,
    CAN_CONTROL_V0_REJECT_TOKEN = 4,
    CAN_CONTROL_V0_REJECT_SEQUENCE = 5,
    CAN_CONTROL_V0_REJECT_UNSAFE = 6,
    CAN_CONTROL_V0_REJECT_TIMEOUT = 7,
    CAN_CONTROL_V0_REJECT_NOT_ARMED = 8,
    CAN_CONTROL_V0_REJECT_DISABLED = 9
} CanControlV0_Decision;

typedef struct {
    uint8_t estop_released;
    uint8_t power_stage_feedback_valid;
    uint8_t encoder_valid;
    uint8_t current_sensor_valid;
    uint8_t vbus_valid;
    uint8_t recipe_validated;
    uint8_t firmware_confirmed;
    uint8_t bus_healthy;
    uint8_t motor_idle;
    uint8_t rotor_stationary;
    uint8_t fault_latched;
    uint8_t analog_safe_latched;
} CanControlV0_Safety;

typedef struct {
    uint16_t session_token;
    uint16_t last_sequence;
    uint16_t armed_recipe_id;
    uint32_t armed_at_ms;
    uint8_t sequence_seen;
    uint8_t armed;
} CanControlV0_Session;

typedef struct {
    uint8_t opcode;
    uint16_t sequence;
    uint8_t decision;
    uint8_t motor_mode;
    uint16_t session_token;
} CanControlV0_Reply;

/* Returns 1 only for a standard data frame with the exact v0 layout. */
uint8_t CanControlV0_ParseRequest(uint32_t id, uint8_t extended,
                                  uint8_t remote, uint8_t error, uint8_t dlc,
                                  const uint8_t *data, CanControlV0_Request *out);
uint8_t CanControlV0_EncodeRequest(const CanControlV0_Request *request,
                                   uint8_t out[8]);
uint8_t CanControlV0_ParseReply(uint32_t id, uint8_t extended,
                                uint8_t remote, uint8_t error, uint8_t dlc,
                                const uint8_t *data, CanControlV0_Reply *out);
uint8_t CanControlV0_EncodeReply(const CanControlV0_Reply *reply,
                                 uint8_t out[8]);

void CanControlV0_Reset(CanControlV0_Session *session, uint16_t token);
/* Evaluates an intent only. It never calls motor, HAL, CAN, or power code. */
CanControlV0_Decision CanControlV0_Evaluate(CanControlV0_Session *session,
                                            const CanControlV0_Safety *safety,
                                            const CanControlV0_Request *request,
                                            uint32_t now_ms);
/* Permanent non-actuating gate for integration tests. Never returns an intent. */
CanControlV0_Decision CanControlV0_EvaluateDisabled(CanControlV0_Session *session,
                                                    const CanControlV0_Request *request);

#ifdef __cplusplus
}
#endif

#endif
