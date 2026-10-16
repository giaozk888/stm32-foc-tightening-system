/* Included by both normal A/B applications after SystemPreflight_FailMask.
 * ProtocolTask is the only command producer; TighteningTask consumes the
 * existing mailbox. UART and future qualified RPC use identical checks.
 * This is not a multi-producer queue or a hardware safety controller. */
typedef enum {
    MOTOR_START_ACCEPTED = 0,
    MOTOR_START_SAFE,
    MOTOR_START_TRIAL,
    MOTOR_START_FAULT,
    MOTOR_START_BUSY,
    MOTOR_START_MOVING,
    MOTOR_START_PREFLIGHT
} MotorStartResult;

static MotorStartResult MotorJob_QueueStart(uint32_t request_id, uint8_t routed,
                                            uint16_t source_node) {
#if defined(FOC_LATEST_ORIGINAL_FSM)
    if (routed || !protocol_esp_ping_uart_local || !LatestOriginal_Ready())
        return MOTOR_START_SAFE;
#endif
    if (analog_safe_latched != 0U)
        return MOTOR_START_SAFE;
    if (BootHealth_IsCurrentTrial() != 0U)
        return MOTOR_START_TRIAL;
    if ((adc_fault != 0U) || (foc_fault != 0U))
        return MOTOR_START_FAULT;
    if ((Tightening_IsBusy() != 0U) || (tightening_start_request != 0U))
        return MOTOR_START_BUSY;
    uint32_t mask = SystemPreflight_FailMask();
    if ((mask & PREFLIGHT_FAIL_SPEED) != 0U)
        return MOTOR_START_MOVING;
    if (mask != 0U)
        return MOTOR_START_PREFLIGHT;
    tightening_start_request_id = request_id;
    tightening_start_request_routed = routed;
    tightening_start_request_source_node = routed ? source_node : 0U;
    __DMB();
    tightening_start_request = 1U;
    return MOTOR_START_ACCEPTED;
}

static void MotorJob_QueueStop(uint32_t request_id) {
#if defined(FOC_LATEST_ORIGINAL_FSM)
    /* Close power immediately; the original FSM still consumes/reports STOP. */
    ProtectedLoop_Stop();
#endif
    tightening_stop_request_id = request_id;
    __DMB();
    tightening_stop_request = 1U;
}

static void MotorJob_HandleUartStart(uint32_t request_id) {
    const MotorStartResult result =
        MotorJob_QueueStart(request_id, protocol_reply_route_active, protocol_reply_route_dst);
    if (result == MOTOR_START_ACCEPTED) {
        char reply[64];
        (void)Protocol_SendFormatted(reply, sizeof(reply), "%lu OK START QUEUED\r\n",
                                     (unsigned long)request_id);
        return;
    }
    static const uint32_t codes[] = {0,
                                     PROTO_ERR_NOT_READY,
                                     PROTO_ERR_FW_STATE,
                                     PROTO_ERR_FAULT,
                                     PROTO_ERR_BUSY,
                                     PROTO_ERR_ROTOR_MOVING,
                                     PROTO_ERR_NOT_READY};
    static const char *const names[] = {
        "",     "ANALOG_SAFE_LATCHED", "TRIAL_NOT_CONFIRMED", "FAULT",
        "BUSY", "ROTOR_MOVING",        "PREFLIGHT_NOT_READY"};
    Protocol_SendError(request_id, codes[result], names[result]);
}

#if defined(CAN_MOTOR_CONTROL_SERVICE)
#include "motor_control.h"
static MotorControlSession motor_rpc_session;

static void MotorRpc_LocalSnapshot(void *context, MotorControlView *view) {
    (void)context;
    TightenParams_t params;
    memset(view, 0, sizeof(*view));
    taskENTER_CRITICAL();
    params = recipe_state.params;
    view->uptime_ms = HAL_GetTick();
    view->preflight = SystemPreflight_FailMask();
    view->mode = (uint32_t)motor_control_mode;
    view->busy = Tightening_IsBusy() || tightening_start_request;
    view->fault_reason = foc_fault_reason;
    view->safe_latched = analog_safe_latched != 0U;
    view->job_id =
        tightening_start_request ? tightening_start_request_id : tightening_cycle_request_id;
    view->job_state = (adc_fault || foc_fault)                             ? MOTOR_JOB_FAULT
                      : tightening_start_request                           ? MOTOR_JOB_QUEUED
                      : view->busy                                         ? MOTOR_JOB_RUNNING
                      : tightening_last_outcome == TIGHTEN_OUTCOME_OK      ? MOTOR_JOB_DONE
                      : tightening_last_outcome == TIGHTEN_OUTCOME_STOPPED ? MOTOR_JOB_STOPPED
                      : tightening_last_outcome != TIGHTEN_OUTCOME_NONE    ? MOTOR_JOB_FAULT
                                                                           : MOTOR_JOB_IDLE;
    taskEXIT_CRITICAL();
    /* Do not infer qualified hardware from GPIO ODR, a UI checkbox, a token,
     * or SELFTEST. There is deliberately NO "unlock" build/runtime switch.
     * boot_id=0 reports that a trusted control boot/session is unavailable. */
    view->blockers = MOTOR_BLOCK_REMOTE_DISABLED | MOTOR_BLOCK_ESTOP_UNVERIFIED |
                     MOTOR_BLOCK_POWER_FEEDBACK_UNVERIFIED | MOTOR_BLOCK_SENSING_UNQUALIFIED |
                     MOTOR_BLOCK_SESSION_UNAVAILABLE | MOTOR_BLOCK_LINK_UNQUALIFIED;
    if (view->preflight)
        view->blockers |= MOTOR_BLOCK_PREFLIGHT;
    if (view->busy)
        view->blockers |= MOTOR_BLOCK_BUSY;
    if (view->safe_latched)
        view->blockers |= MOTOR_BLOCK_SAFE_LATCHED;
    uint32_t crc = 0xffffffffU;
    const uint8_t *bytes = (const uint8_t *)&params;
    for (size_t i = 0; i < sizeof(params); ++i) {
        crc ^= bytes[i];
        for (unsigned bit = 0; bit < 8; ++bit)
            crc = (crc >> 1) ^ ((crc & 1U) ? 0xedb88320U : 0U);
    }
    view->recipe_crc = crc ^ 0xffffffffU;
}

static uint8_t MotorRpc_QueueStart(void *context, uint32_t operation_id) {
    (void)context;
    return MotorJob_QueueStart(operation_id, 0U, 0U) == MOTOR_START_ACCEPTED;
}
static uint8_t MotorRpc_QueueStop(void *context, uint32_t operation_id) {
    (void)context;
    MotorJob_QueueStop(operation_id);
    return 1U;
}
void PW_MotorControl_Invoke(MotorControlOpcode opcode, const MotorControlRequest *request,
                            MotorControlReply *reply) {
    static const MotorControlPort port = {NULL, MotorRpc_LocalSnapshot, MotorRpc_QueueStart,
                                          MotorRpc_QueueStop};
    MotorControl_Dispatch(&motor_rpc_session, &port, opcode, request, reply);
}
#endif
