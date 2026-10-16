#include "can_control_v0.h"

#ifdef NDEBUG
#undef NDEBUG
#endif
#include <assert.h>

static CanControlV0_Safety ready_safety(void)
{
    CanControlV0_Safety safe = {0};
    safe.estop_released = 1U;
    safe.power_stage_feedback_valid = 1U;
    safe.encoder_valid = 1U;
    safe.current_sensor_valid = 1U;
    safe.vbus_valid = 1U;
    safe.recipe_validated = 1U;
    safe.firmware_confirmed = 1U;
    safe.bus_healthy = 1U;
    safe.motor_idle = 1U;
    safe.rotor_stationary = 1U;
    return safe;
}

static void frame_contract(void)
{
    const CanControlV0_Request arm = {CAN_CONTROL_V0_ARM, 0x1234U, 0x5678U, 0x9ABCU};
    CanControlV0_Request parsed = {0};
    const CanControlV0_Reply reply = {
        CAN_CONTROL_V0_ARM, 0x1234U, CAN_CONTROL_V0_ARMED, 0U, 0x5678U};
    CanControlV0_Reply parsed_reply = {0};
    uint8_t bytes[8] = {0};

    assert(CanControlV0_EncodeRequest(&arm, bytes) == 1U);
    assert(bytes[0] == 1U && bytes[1] == CAN_CONTROL_V0_ARM);
    assert(bytes[2] == 0x34U && bytes[3] == 0x12U);
    assert(bytes[4] == 0x78U && bytes[5] == 0x56U);
    assert(bytes[6] == 0xBCU && bytes[7] == 0x9AU);
    assert(CanControlV0_ParseRequest(CAN_CONTROL_V0_REQUEST_ID, 0U, 0U, 0U,
                                     8U, bytes, &parsed) == 1U);
    assert(parsed.sequence == arm.sequence && parsed.recipe_id == arm.recipe_id);
    assert(CanControlV0_ParseRequest(0x180U, 0U, 0U, 0U, 8U, bytes, &parsed) == 0U);
    assert(CanControlV0_ParseRequest(CAN_CONTROL_V0_REQUEST_ID, 1U, 0U, 0U,
                                     8U, bytes, &parsed) == 0U);
    assert(CanControlV0_ParseRequest(CAN_CONTROL_V0_REQUEST_ID, 0U, 1U, 0U,
                                     8U, bytes, &parsed) == 0U);
    assert(CanControlV0_ParseRequest(CAN_CONTROL_V0_REQUEST_ID, 0U, 0U, 1U,
                                     8U, bytes, &parsed) == 0U);
    assert(CanControlV0_ParseRequest(CAN_CONTROL_V0_REQUEST_ID, 0U, 0U, 0U,
                                     7U, bytes, &parsed) == 0U);
    bytes[0] = 2U;
    assert(CanControlV0_ParseRequest(CAN_CONTROL_V0_REQUEST_ID, 0U, 0U, 0U,
                                     8U, bytes, &parsed) == 0U);
    bytes[0] = 1U;
    bytes[1] = 99U;
    assert(CanControlV0_ParseRequest(CAN_CONTROL_V0_REQUEST_ID, 0U, 0U, 0U,
                                     8U, bytes, &parsed) == 0U);
    assert(CanControlV0_EncodeReply(&reply, bytes) == 1U);
    assert(CanControlV0_ParseReply(CAN_CONTROL_V0_REPLY_ID, 0U, 0U, 0U,
                                   8U, bytes, &parsed_reply) == 1U);
    assert(parsed_reply.opcode == reply.opcode);
    assert(parsed_reply.sequence == reply.sequence);
    assert(parsed_reply.decision == reply.decision);
    assert(parsed_reply.session_token == reply.session_token);
    assert(CanControlV0_ParseReply(CAN_CONTROL_V0_REQUEST_ID, 0U, 0U, 0U,
                                   8U, bytes, &parsed_reply) == 0U);
}

static void fail_closed_and_intents(void)
{
    CanControlV0_Session session;
    CanControlV0_Safety safe = ready_safety();
    CanControlV0_Request arm = {CAN_CONTROL_V0_ARM, 100U, 0xBEEFU, 7U};
    CanControlV0_Request start = {CAN_CONTROL_V0_START, 101U, 0xBEEFU, 7U};
    CanControlV0_Request stop = {CAN_CONTROL_V0_STOP, 0U, 0U, 0U};

    CanControlV0_Reset(&session, 0xBEEFU);
    safe.power_stage_feedback_valid = 0U;
    assert(CanControlV0_Evaluate(&session, &safe, &arm, 1000U) ==
           CAN_CONTROL_V0_REJECT_UNSAFE);
    assert(session.armed == 0U);
    safe = ready_safety();
    safe.bus_healthy = 0U;
    assert(CanControlV0_Evaluate(&session, &safe, &arm, 1000U) ==
           CAN_CONTROL_V0_REJECT_UNSAFE);
    safe = ready_safety();
    safe.analog_safe_latched = 1U;
    assert(CanControlV0_Evaluate(&session, &safe, &arm, 1000U) ==
           CAN_CONTROL_V0_REJECT_UNSAFE);
    safe = ready_safety();
    safe.fault_latched = 1U;
    assert(CanControlV0_Evaluate(&session, &safe, &arm, 1000U) ==
           CAN_CONTROL_V0_REJECT_UNSAFE);
    safe = ready_safety();

    arm.session_token = 0xBADU;
    assert(CanControlV0_Evaluate(&session, &safe, &arm, 1000U) ==
           CAN_CONTROL_V0_REJECT_TOKEN);
    arm.session_token = 0xBEEFU;
    assert(CanControlV0_Evaluate(&session, &safe, &start, 1001U) ==
           CAN_CONTROL_V0_REJECT_NOT_ARMED);
    assert(CanControlV0_Evaluate(&session, &safe, &arm, 1000U) ==
           CAN_CONTROL_V0_ARMED);
    assert(session.armed == 1U);
    assert(CanControlV0_Evaluate(&session, &safe, &start, 1200U) ==
           CAN_CONTROL_V0_START_INTENT);
    assert(session.armed == 0U);
    assert(CanControlV0_Evaluate(&session, &safe, &start, 1201U) ==
           CAN_CONTROL_V0_REJECT_SEQUENCE);
    assert(CanControlV0_Evaluate(&session, &safe, &arm, 1202U) ==
           CAN_CONTROL_V0_REJECT_SEQUENCE);

    /* STOP remains idempotent even if token, bus health or faults disagree. */
    safe.bus_healthy = 0U;
    safe.fault_latched = 1U;
    assert(CanControlV0_Evaluate(&session, &safe, &stop, 1203U) ==
           CAN_CONTROL_V0_STOP_INTENT);
    assert(CanControlV0_Evaluate(&session, &safe, &stop, 1204U) ==
           CAN_CONTROL_V0_STOP_INTENT);
    assert(session.session_token == 0U);
    safe = ready_safety();
    assert(CanControlV0_Evaluate(&session, &safe, &arm, 1205U) ==
           CAN_CONTROL_V0_REJECT_TOKEN);
}

static void expiry_recipe_and_wrap(void)
{
    CanControlV0_Session session;
    CanControlV0_Safety safe = ready_safety();
    CanControlV0_Request arm = {CAN_CONTROL_V0_ARM, 65535U, 0x1234U, 9U};
    CanControlV0_Request start = {CAN_CONTROL_V0_START, 0U, 0x1234U, 9U};

    CanControlV0_Reset(&session, 0x1234U);
    assert(CanControlV0_Evaluate(&session, &safe, &arm, 0xFFFFFF00U) ==
           CAN_CONTROL_V0_ARMED);
    start.recipe_id = 10U;
    assert(CanControlV0_Evaluate(&session, &safe, &start, 0xFFFFFF50U) ==
           CAN_CONTROL_V0_REJECT_SEQUENCE);
    assert(session.armed == 0U);

    CanControlV0_Reset(&session, 0x1234U);
    assert(CanControlV0_Evaluate(&session, &safe, &arm, 0xFFFFFF00U) ==
           CAN_CONTROL_V0_ARMED);
    start.recipe_id = 9U;
    assert(CanControlV0_Evaluate(&session, &safe, &start, 0x00000000U) ==
           CAN_CONTROL_V0_START_INTENT); /* 32-bit millisecond wrap. */

    CanControlV0_Reset(&session, 0x1234U);
    assert(CanControlV0_Evaluate(&session, &safe, &arm, 1000U) ==
           CAN_CONTROL_V0_ARMED);
    assert(CanControlV0_Evaluate(&session, &safe, &start, 1501U) ==
           CAN_CONTROL_V0_REJECT_TIMEOUT);
    assert(session.armed == 0U);

    CanControlV0_Reset(&session, 0x1234U);
    assert(CanControlV0_Evaluate(&session, &safe, &arm, 1000U) ==
           CAN_CONTROL_V0_ARMED);
    safe.estop_released = 0U;
    assert(CanControlV0_Evaluate(&session, &safe, &start, 1200U) ==
           CAN_CONTROL_V0_REJECT_UNSAFE);
    assert(session.armed == 0U);
}

static void every_safety_input_is_mandatory(void)
{
    CanControlV0_Safety safe = ready_safety();
    CanControlV0_Session session;
    CanControlV0_Request arm = {CAN_CONTROL_V0_ARM, 11U, 0xA55AU, 3U};
    uint8_t *required[] = {
        &safe.estop_released, &safe.power_stage_feedback_valid,
        &safe.encoder_valid, &safe.current_sensor_valid,
        &safe.vbus_valid, &safe.recipe_validated,
        &safe.firmware_confirmed, &safe.bus_healthy,
        &safe.motor_idle, &safe.rotor_stationary};
    unsigned int i;

    for (i = 0U; i < sizeof(required) / sizeof(required[0]); ++i)
    {
        CanControlV0_Reset(&session, 0xA55AU);
        *required[i] = 0U;
        assert(CanControlV0_Evaluate(&session, &safe, &arm, 100U) ==
               CAN_CONTROL_V0_REJECT_UNSAFE);
        assert(session.armed == 0U);
        *required[i] = 1U;
    }
    CanControlV0_Reset(&session, 0xA55AU);
    safe.fault_latched = 1U;
    assert(CanControlV0_Evaluate(&session, &safe, &arm, 100U) ==
           CAN_CONTROL_V0_REJECT_UNSAFE);
    safe.fault_latched = 0U;
    safe.analog_safe_latched = 1U;
    assert(CanControlV0_Evaluate(&session, &safe, &arm, 100U) ==
           CAN_CONTROL_V0_REJECT_UNSAFE);
    safe.analog_safe_latched = 0U;
    assert(CanControlV0_Evaluate(&session, &safe, &arm, 100U) ==
           CAN_CONTROL_V0_ARMED);
}

static void disabled_gate_never_intends_action(void)
{
    CanControlV0_Session session;
    CanControlV0_Request request = {CAN_CONTROL_V0_ARM, 1U, 0x1234U, 7U};
    CanControlV0_Reply reply = {CAN_CONTROL_V0_ARM, 1U,
                                CAN_CONTROL_V0_REJECT_DISABLED, 0U, 0U};
    CanControlV0_Reply decoded = {0};
    uint8_t bytes[8] = {0};

    CanControlV0_Reset(&session, 0x1234U);
    session.armed = 1U;
    assert(CanControlV0_EvaluateDisabled(&session, &request) ==
           CAN_CONTROL_V0_REJECT_DISABLED);
    assert(session.armed == 0U && session.session_token == 0U);
    request.opcode = CAN_CONTROL_V0_START;
    assert(CanControlV0_EvaluateDisabled(&session, &request) ==
           CAN_CONTROL_V0_REJECT_DISABLED);
    request.opcode = CAN_CONTROL_V0_STOP;
    request.recipe_id = 0U;
    assert(CanControlV0_EvaluateDisabled(&session, &request) ==
           CAN_CONTROL_V0_REJECT_DISABLED);
    assert(CanControlV0_EncodeReply(&reply, bytes) == 1U);
    assert(CanControlV0_ParseReply(CAN_CONTROL_V0_REPLY_ID, 0U, 0U, 0U,
                                   8U, bytes, &decoded) == 1U);
    assert(decoded.decision == CAN_CONTROL_V0_REJECT_DISABLED);
}

int main(void)
{
    frame_contract();
    fail_closed_and_intents();
    expiry_recipe_and_wrap();
    every_safety_input_is_mandatory();
    disabled_gate_never_intends_action();
    return 0;
}
