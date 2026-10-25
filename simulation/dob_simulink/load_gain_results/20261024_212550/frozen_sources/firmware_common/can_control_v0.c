#include "can_control_v0.h"

#include <stddef.h>

static uint16_t read_u16(const uint8_t *bytes)
{
    return (uint16_t)((uint16_t)bytes[0] | ((uint16_t)bytes[1] << 8));
}

static void write_u16(uint8_t *bytes, uint16_t value)
{
    bytes[0] = (uint8_t)value;
    bytes[1] = (uint8_t)(value >> 8);
}

static uint8_t valid_opcode(uint8_t opcode)
{
    return (uint8_t)((opcode == CAN_CONTROL_V0_ARM) ||
                     (opcode == CAN_CONTROL_V0_START) ||
                     (opcode == CAN_CONTROL_V0_STOP));
}

static uint8_t valid_request(const CanControlV0_Request *request)
{
    if ((request == NULL) || (valid_opcode(request->opcode) == 0U)) return 0U;
    if (request->opcode == CAN_CONTROL_V0_STOP)
        return (uint8_t)(request->recipe_id == 0U);
    return (uint8_t)(request->recipe_id != 0U);
}

static uint8_t safe_to_arm_or_start(const CanControlV0_Safety *safety)
{
    return (uint8_t)((safety != NULL) &&
        (safety->estop_released == 1U) &&
        (safety->power_stage_feedback_valid == 1U) &&
        (safety->encoder_valid == 1U) &&
        (safety->current_sensor_valid == 1U) &&
        (safety->vbus_valid == 1U) &&
        (safety->recipe_validated == 1U) &&
        (safety->firmware_confirmed == 1U) &&
        (safety->bus_healthy == 1U) &&
        (safety->motor_idle == 1U) &&
        (safety->rotor_stationary == 1U) &&
        (safety->fault_latched == 0U) &&
        (safety->analog_safe_latched == 0U));
}

static uint8_t sequence_forward(uint16_t next, uint16_t previous)
{
    const uint16_t delta = (uint16_t)(next - previous);
    return (uint8_t)((delta != 0U) && (delta < 0x8000U));
}

uint8_t CanControlV0_ParseRequest(uint32_t id, uint8_t extended,
                                  uint8_t remote, uint8_t error, uint8_t dlc,
                                  const uint8_t *data, CanControlV0_Request *out)
{
    CanControlV0_Request candidate;
    if ((id != CAN_CONTROL_V0_REQUEST_ID) || (extended != 0U) ||
        (remote != 0U) || (error != 0U) || (dlc != 8U) ||
        (data == NULL) || (out == NULL) ||
        (data[0] != CAN_CONTROL_V0_VERSION)) return 0U;
    candidate.opcode = data[1];
    candidate.sequence = read_u16(&data[2]);
    candidate.session_token = read_u16(&data[4]);
    candidate.recipe_id = read_u16(&data[6]);
    if (valid_request(&candidate) == 0U) return 0U;
    *out = candidate;
    return 1U;
}

uint8_t CanControlV0_EncodeRequest(const CanControlV0_Request *request,
                                   uint8_t out[8])
{
    if ((valid_request(request) == 0U) || (out == NULL)) return 0U;
    out[0] = CAN_CONTROL_V0_VERSION;
    out[1] = request->opcode;
    write_u16(&out[2], request->sequence);
    write_u16(&out[4], request->session_token);
    write_u16(&out[6], request->recipe_id);
    return 1U;
}

uint8_t CanControlV0_ParseReply(uint32_t id, uint8_t extended,
                                uint8_t remote, uint8_t error, uint8_t dlc,
                                const uint8_t *data, CanControlV0_Reply *out)
{
    CanControlV0_Reply candidate;
    if ((id != CAN_CONTROL_V0_REPLY_ID) || (extended != 0U) ||
        (remote != 0U) || (error != 0U) || (dlc != 8U) ||
        (data == NULL) || (out == NULL) ||
        (data[0] != CAN_CONTROL_V0_VERSION) ||
        (valid_opcode(data[1]) == 0U) ||
        (data[4] < CAN_CONTROL_V0_STOP_INTENT) ||
        (data[4] > CAN_CONTROL_V0_REJECT_DISABLED) ||
        (data[5] > 3U)) return 0U;
    candidate.opcode = data[1];
    candidate.sequence = read_u16(&data[2]);
    candidate.decision = data[4];
    candidate.motor_mode = data[5];
    candidate.session_token = read_u16(&data[6]);
    *out = candidate;
    return 1U;
}

uint8_t CanControlV0_EncodeReply(const CanControlV0_Reply *reply,
                                 uint8_t out[8])
{
    if ((reply == NULL) || (out == NULL) ||
        (valid_opcode(reply->opcode) == 0U) ||
        (reply->decision < CAN_CONTROL_V0_STOP_INTENT) ||
        (reply->decision > CAN_CONTROL_V0_REJECT_DISABLED) ||
        (reply->motor_mode > 3U)) return 0U;
    out[0] = CAN_CONTROL_V0_VERSION;
    out[1] = reply->opcode;
    write_u16(&out[2], reply->sequence);
    out[4] = reply->decision;
    out[5] = reply->motor_mode;
    write_u16(&out[6], reply->session_token);
    return 1U;
}

void CanControlV0_Reset(CanControlV0_Session *session, uint16_t token)
{
    if (session == NULL) return;
    session->session_token = token;
    session->last_sequence = 0U;
    session->armed_recipe_id = 0U;
    session->armed_at_ms = 0U;
    session->sequence_seen = 0U;
    session->armed = 0U;
}

CanControlV0_Decision CanControlV0_EvaluateDisabled(CanControlV0_Session *session,
                                                    const CanControlV0_Request *request)
{
    if ((session == NULL) || (valid_request(request) == 0U))
        return CAN_CONTROL_V0_INVALID;
    CanControlV0_Reset(session, 0U);
    return CAN_CONTROL_V0_REJECT_DISABLED;
}

CanControlV0_Decision CanControlV0_Evaluate(CanControlV0_Session *session,
                                            const CanControlV0_Safety *safety,
                                            const CanControlV0_Request *request,
                                            uint32_t now_ms)
{
    if ((session == NULL) || (valid_request(request) == 0U))
        return CAN_CONTROL_V0_INVALID;

    /* STOP is fail-safe, idempotent and does not depend on an active lease. */
    if (request->opcode == CAN_CONTROL_V0_STOP)
    {
        session->armed = 0U;
        session->session_token = 0U; /* A fresh local session is required. */
        return CAN_CONTROL_V0_STOP_INTENT;
    }

    if ((session->session_token == 0U) ||
        (request->session_token != session->session_token))
    {
        session->armed = 0U;
        return CAN_CONTROL_V0_REJECT_TOKEN;
    }
    if ((session->sequence_seen != 0U) &&
        (sequence_forward(request->sequence, session->last_sequence) == 0U))
    {
        session->armed = 0U;
        return CAN_CONTROL_V0_REJECT_SEQUENCE;
    }
    if (safe_to_arm_or_start(safety) == 0U)
    {
        session->armed = 0U;
        return CAN_CONTROL_V0_REJECT_UNSAFE;
    }

    if (request->opcode == CAN_CONTROL_V0_ARM)
    {
        session->last_sequence = request->sequence;
        session->sequence_seen = 1U;
        session->armed_recipe_id = request->recipe_id;
        session->armed_at_ms = now_ms;
        session->armed = 1U;
        return CAN_CONTROL_V0_ARMED;
    }
    if (session->armed == 0U) return CAN_CONTROL_V0_REJECT_NOT_ARMED;
    if ((request->recipe_id != session->armed_recipe_id) ||
        (request->sequence != (uint16_t)(session->last_sequence + 1U)))
    {
        session->armed = 0U;
        return CAN_CONTROL_V0_REJECT_SEQUENCE;
    }
    if ((uint32_t)(now_ms - session->armed_at_ms) > CAN_CONTROL_V0_ARM_WINDOW_MS)
    {
        session->armed = 0U;
        return CAN_CONTROL_V0_REJECT_TIMEOUT;
    }
    session->armed = 0U;
    session->last_sequence = request->sequence;
    session->sequence_seen = 1U;
    return CAN_CONTROL_V0_START_INTENT;
}
