#ifndef MOTOR_CONTROL_H
#define MOTOR_CONTROL_H
#include <stdint.h>

/* Application protocol, not authentication or a certified safety function.
 * Only trusted LOCAL port callbacks may supply the view and submit jobs.
 * One ProtocolTask owns each session. No allocation, HAL or Flash access. */
#define MOTOR_CONTROL_VERSION 1U
#define MOTOR_CONTROL_ARM_MS 5000U
#define MOTOR_CONTROL_REQUEST_WORDS 5U
#define MOTOR_CONTROL_REPLY_WORDS 15U

typedef enum {
    MOTOR_RPC_ARM = 1,
    MOTOR_RPC_START = 2,
    MOTOR_RPC_STOP = 3,
    MOTOR_RPC_STATUS = 4
} MotorControlOpcode;
typedef enum {
    MOTOR_RPC_OK = 0,
    MOTOR_RPC_ARMED,
    MOTOR_RPC_QUEUED,
    MOTOR_RPC_DUPLICATE,
    MOTOR_RPC_DISABLED,
    MOTOR_RPC_UNSAFE,
    MOTOR_RPC_BAD_SESSION,
    MOTOR_RPC_BAD_RECIPE,
    MOTOR_RPC_NOT_ARMED,
    MOTOR_RPC_EXPIRED,
    MOTOR_RPC_BAD_TOKEN,
    MOTOR_RPC_REPLAY,
    MOTOR_RPC_QUEUE_REJECTED,
    MOTOR_RPC_INVALID
} MotorControlDecision;
enum {
    MOTOR_BLOCK_REMOTE_DISABLED = 1U << 0,
    MOTOR_BLOCK_ESTOP_UNVERIFIED = 1U << 1,
    MOTOR_BLOCK_POWER_FEEDBACK_UNVERIFIED = 1U << 2,
    MOTOR_BLOCK_SENSING_UNQUALIFIED = 1U << 3,
    MOTOR_BLOCK_SESSION_UNAVAILABLE = 1U << 4,
    MOTOR_BLOCK_LINK_UNQUALIFIED = 1U << 5,
    MOTOR_BLOCK_PREFLIGHT = 1U << 6,
    MOTOR_BLOCK_BUSY = 1U << 7,
    MOTOR_BLOCK_SAFE_LATCHED = 1U << 8
};
typedef enum {
    MOTOR_JOB_IDLE = 0,
    MOTOR_JOB_QUEUED,
    MOTOR_JOB_RUNNING,
    MOTOR_JOB_DONE,
    MOTOR_JOB_STOPPED,
    MOTOR_JOB_FAULT
} MotorJobState;
typedef struct {
    uint32_t version, operation_id, boot_id, recipe_crc, arm_token;
} MotorControlRequest;
typedef struct {
    uint32_t blockers, preflight, boot_id, recipe_crc, job_id, job_state;
    uint32_t mode, busy, fault_reason, safe_latched, uptime_ms;
} MotorControlView;
typedef struct {
    uint32_t decision, operation_id, arm_token;
    MotorControlView view;
} MotorControlReply;
typedef struct {
    uint32_t boot_id, arm_token, armed_at_ms, armed_recipe, nonce;
    uint32_t last_start_id, last_recipe, last_stop_id;
    uint8_t armed;
} MotorControlSession;
typedef struct {
    void *context;
    void (*snapshot)(void *, MotorControlView *);
    uint8_t (*submit_start)(void *, uint32_t);
    uint8_t (*submit_stop)(void *, uint32_t);
} MotorControlPort;

#ifdef __cplusplus
extern "C" {
#endif
void MotorControl_Reset(MotorControlSession *session);
void MotorControl_Dispatch(MotorControlSession *session, const MotorControlPort *port,
                           MotorControlOpcode opcode, const MotorControlRequest *request,
                           MotorControlReply *reply);
/* Normal firmware port is permanently fail-closed for remote ARM/START/STOP.
 * Enabling the SERVICE does not enable actuator authority. */
void PW_MotorControl_Invoke(MotorControlOpcode opcode, const MotorControlRequest *request,
                            MotorControlReply *reply);
#ifdef __cplusplus
}
#endif
#endif
