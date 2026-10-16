/* Compile the EXACT shared A/B port with mocked locals, never a device. */
#include "motor_control.h"
#include "tighten_params.h"
#include <assert.h>
#include <stddef.h>
#include <string.h>
#include <stdarg.h>
#include <stdio.h>
#define taskENTER_CRITICAL() ((void)0)
#define taskEXIT_CRITICAL() ((void)0)
#define __DMB() ((void)0)
#define PREFLIGHT_FAIL_SPEED 1U
enum {
    PROTO_ERR_NOT_READY = 104,
    PROTO_ERR_FW_STATE = 109,
    PROTO_ERR_FAULT = 105,
    PROTO_ERR_BUSY = 101,
    PROTO_ERR_ROTOR_MOVING = 106
};
enum { TIGHTEN_OUTCOME_NONE, TIGHTEN_OUTCOME_OK, TIGHTEN_OUTCOME_STOPPED };
static uint32_t analog_safe_latched, adc_fault, foc_fault, foc_fault_reason, trial, busy, preflight;
static uint32_t tightening_start_request, tightening_start_request_id;
static uint32_t tightening_start_request_routed, tightening_start_request_source_node;
static uint32_t tightening_stop_request, tightening_stop_request_id;
static uint32_t tightening_cycle_request_id, tightening_last_outcome, motor_control_mode;
static uint8_t protocol_reply_route_active;
static uint16_t protocol_reply_route_dst;
static struct {
    TightenParams_t params;
} recipe_state = {TIGHTEN_PARAMS_DEFAULT_INITIALIZER};
static uint32_t last_error;
static const char *last_name;
static uint32_t HAL_GetTick(void) {
    return 123;
}
static uint8_t BootHealth_IsCurrentTrial(void) {
    return (uint8_t)trial;
}
static uint8_t Tightening_IsBusy(void) {
    return (uint8_t)busy;
}
static uint32_t SystemPreflight_FailMask(void) {
    return preflight;
}
static uint8_t Protocol_SendFormatted(char *buffer, size_t capacity, const char *fmt, ...) {
    va_list args;
    va_start(args, fmt);
    vsnprintf(buffer, capacity, fmt, args);
    va_end(args);
    return 1;
}
static void Protocol_SendError(uint32_t id, uint32_t code, const char *name) {
    (void)id;
    last_error = code;
    last_name = name;
}
#include "motor_job_port.inc"
int main(void) {
    MotorControlRequest req = {1, 55, 0, 0, 0};
    MotorControlReply reply;
    for (int op = MOTOR_RPC_ARM; op <= MOTOR_RPC_STATUS; ++op) {
        PW_MotorControl_Invoke((MotorControlOpcode)op, &req, &reply);
        assert(reply.decision == (op == MOTOR_RPC_STATUS ? MOTOR_RPC_OK : MOTOR_RPC_DISABLED));
        assert(reply.view.blockers & MOTOR_BLOCK_REMOTE_DISABLED);
        assert(reply.view.boot_id == 0 && reply.view.recipe_crc);
        assert(!tightening_start_request && !tightening_stop_request);
    }
    struct {
        uint32_t *flag;
        uint32_t value, code;
        const char *name;
    } cases[] = {{&analog_safe_latched, 1, 104, "ANALOG_SAFE_LATCHED"},
                 {&trial, 1, 109, "TRIAL_NOT_CONFIRMED"},
                 {&adc_fault, 1, 105, "FAULT"},
                 {&foc_fault, 1, 105, "FAULT"},
                 {&busy, 1, 101, "BUSY"},
                 {&tightening_start_request, 1, 101, "BUSY"},
                 {&preflight, 1, 106, "ROTOR_MOVING"},
                 {&preflight, 2, 104, "PREFLIGHT_NOT_READY"}};
    for (size_t i = 0; i < sizeof(cases) / sizeof(cases[0]); ++i) {
        *cases[i].flag = cases[i].value;
        MotorJob_HandleUartStart(4);
        assert(last_error == cases[i].code && strcmp(last_name, cases[i].name) == 0);
        *cases[i].flag = 0;
    }
    protocol_reply_route_active = 1;
    protocol_reply_route_dst = 3;
    MotorJob_HandleUartStart(44);
    assert(tightening_start_request == 1 && tightening_start_request_id == 44);
    assert(tightening_start_request_routed == 1 && tightening_start_request_source_node == 3);
    MotorJob_QueueStop(45);
    assert(tightening_stop_request && tightening_stop_request_id == 45);
    puts("PASS: actual MCU port rejects all remote actions; legacy UART gate/route preserved");
}
