#include "can_shadow_diag.h"

#include <stddef.h>

static uint16_t read_u16(const uint8_t *data)
{
    return (uint16_t)((uint16_t)data[0] | ((uint16_t)data[1] << 8));
}

static void write_u16(uint8_t *data, uint16_t value)
{
    data[0] = (uint8_t)value;
    data[1] = (uint8_t)(value >> 8);
}

static uint8_t forward(uint16_t next, uint16_t previous)
{
    const uint16_t delta = (uint16_t)(next - previous);
    return (uint8_t)((delta != 0U) && (delta < 0x8000U));
}

uint8_t CanShadow_DecodeRequest(uint32_t id, uint8_t extended,
                                uint8_t remote, uint8_t fd_format,
                                uint8_t dlc, const uint8_t *data,
                                CanShadow_Request *out)
{
    if ((id != CAN_SHADOW_REQUEST_ID) || (extended != 0U) ||
        (remote != 0U) || (fd_format != 0U) || (dlc != 8U) ||
        (data == NULL) || (out == NULL) ||
        (data[0] != CAN_SHADOW_VERSION) ||
        (data[6] != 0xA5U) || (data[7] != 0x5AU)) return 0U;

    out->opcode = data[1];
    out->sequence = read_u16(&data[2]);
    out->test_value = read_u16(&data[4]);
    return 1U;
}

uint8_t CanShadow_EncodeRequest(const CanShadow_Request *request,
                                uint8_t out[8])
{
    if ((request == NULL) || (out == NULL)) return 0U;
    out[0] = CAN_SHADOW_VERSION;
    out[1] = request->opcode;
    write_u16(&out[2], request->sequence);
    write_u16(&out[4], request->test_value);
    out[6] = 0xA5U;
    out[7] = 0x5AU;
    return 1U;
}

uint8_t CanShadow_EncodeReply(const CanShadow_Request *request,
                              CanShadow_Decision decision, uint8_t out[8])
{
    if ((request == NULL) || (out == NULL) ||
        (decision < CAN_SHADOW_PROBE_READY) ||
        (decision > CAN_SHADOW_REJECT_VALUE)) return 0U;
    out[0] = CAN_SHADOW_VERSION;
    out[1] = request->opcode;
    write_u16(&out[2], request->sequence);
    out[4] = (uint8_t)decision;
    out[5] = 0U; /* Reserved: no motor status or actuation claim. */
    out[6] = 0x5AU;
    out[7] = 0xA5U;
    return 1U;
}

void CanShadow_Reset(CanShadow_State *state)
{
    if (state == NULL) return;
    state->last_sequence = 0U;
    state->opened_at_ms = 0U;
    state->sequence_seen = 0U;
    state->probe_open = 0U;
    state->probe_expired = 0U;
}

uint8_t CanShadow_Tick(CanShadow_State *state, uint32_t now_ms)
{
    if ((state == NULL) || (state->probe_open == 0U) ||
        ((uint32_t)(now_ms - state->opened_at_ms) <= CAN_SHADOW_WINDOW_MS))
        return 0U;
    state->probe_open = 0U;
    state->probe_expired = 1U;
    return 1U;
}

CanShadow_Decision CanShadow_Evaluate(CanShadow_State *state,
                                      const CanShadow_Request *request,
                                      uint32_t now_ms)
{
    if ((state == NULL) || (request == NULL)) return CAN_SHADOW_REJECT_OPCODE;
    (void)CanShadow_Tick(state, now_ms);

    /* STOP_TEST is intentionally idempotent and only clears shadow state.
       The physical emergency stop and motor state are untouched. */
    if (request->opcode == CAN_SHADOW_STOP_TEST) {
        if (request->test_value != 0U) return CAN_SHADOW_REJECT_VALUE;
        state->probe_open = 0U;
        state->probe_expired = 0U;
        state->sequence_seen = 0U;
        state->last_sequence = 0U;
        return CAN_SHADOW_STOP_OBSERVED_NO_ACTION;
    }
    if ((request->opcode != CAN_SHADOW_PROBE) &&
        (request->opcode != CAN_SHADOW_CHECK_VALUE))
        return CAN_SHADOW_REJECT_OPCODE;

    if ((state->sequence_seen != 0U) &&
        (forward(request->sequence, state->last_sequence) == 0U))
        return CAN_SHADOW_REJECT_SEQUENCE;

    if (request->opcode == CAN_SHADOW_PROBE) {
        if (request->test_value != 0U) return CAN_SHADOW_REJECT_VALUE;
        state->last_sequence = request->sequence;
        state->sequence_seen = 1U;
        state->opened_at_ms = now_ms;
        state->probe_open = 1U;
        state->probe_expired = 0U;
        return CAN_SHADOW_PROBE_READY;
    }

    if ((request->test_value == 0U) ||
        (request->test_value > CAN_SHADOW_MAX_TEST_VALUE))
        return CAN_SHADOW_REJECT_RANGE;
    if (state->probe_expired != 0U) return CAN_SHADOW_REJECT_TIMEOUT;
    if (state->probe_open == 0U) return CAN_SHADOW_REJECT_NO_PROBE;
    if (request->sequence != (uint16_t)(state->last_sequence + 1U))
        return CAN_SHADOW_REJECT_SEQUENCE;

    state->last_sequence = request->sequence;
    state->probe_open = 0U;
    return CAN_SHADOW_VALUE_OK_NO_ACTION;
}
