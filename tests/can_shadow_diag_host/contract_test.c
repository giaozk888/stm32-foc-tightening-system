#include "can_shadow_diag.h"

#include <assert.h>
#include <stdint.h>
#include <stdio.h>

static void test_frames(void)
{
    CanShadow_Request request = {CAN_SHADOW_CHECK_VALUE, 0x1234U, 1000U};
    CanShadow_Request decoded = {0};
    uint8_t bytes[8] = {0};

    assert(CanShadow_EncodeRequest(&request, bytes) == 1U);
    assert(bytes[0] == 1U && bytes[1] == 2U);
    assert(bytes[2] == 0x34U && bytes[3] == 0x12U);
    assert(bytes[4] == 0xE8U && bytes[5] == 0x03U);
    assert(bytes[6] == 0xA5U && bytes[7] == 0x5AU);
    assert(CanShadow_DecodeRequest(CAN_SHADOW_REQUEST_ID, 0U, 0U, 0U,
                                   8U, bytes, &decoded) == 1U);
    assert(decoded.opcode == request.opcode &&
           decoded.sequence == request.sequence &&
           decoded.test_value == request.test_value);
    assert(CanShadow_DecodeRequest(0x200U, 0U, 0U, 0U, 8U,
                                   bytes, &decoded) == 0U);
    assert(CanShadow_DecodeRequest(CAN_SHADOW_REQUEST_ID, 1U, 0U, 0U,
                                   8U, bytes, &decoded) == 0U);
    assert(CanShadow_DecodeRequest(CAN_SHADOW_REQUEST_ID, 0U, 1U, 0U,
                                   8U, bytes, &decoded) == 0U);
    assert(CanShadow_DecodeRequest(CAN_SHADOW_REQUEST_ID, 0U, 0U, 1U,
                                   8U, bytes, &decoded) == 0U);
    assert(CanShadow_DecodeRequest(CAN_SHADOW_REQUEST_ID, 0U, 0U, 0U,
                                   7U, bytes, &decoded) == 0U);
    bytes[6] = 0U;
    assert(CanShadow_DecodeRequest(CAN_SHADOW_REQUEST_ID, 0U, 0U, 0U,
                                   8U, bytes, &decoded) == 0U);
    assert(CanShadow_EncodeReply(&request, CAN_SHADOW_VALUE_OK_NO_ACTION,
                                 bytes) == 1U);
    assert(bytes[0] == 1U && bytes[1] == 2U &&
           bytes[2] == 0x34U && bytes[3] == 0x12U &&
           bytes[4] == CAN_SHADOW_VALUE_OK_NO_ACTION &&
           bytes[5] == 0U && bytes[6] == 0x5AU && bytes[7] == 0xA5U);
}

static void test_probe_and_bounds(void)
{
    CanShadow_State state;
    CanShadow_Request probe = {CAN_SHADOW_PROBE, 10U, 0U};
    CanShadow_Request check = {CAN_SHADOW_CHECK_VALUE, 11U, 1000U};
    CanShadow_Reset(&state);
    assert(CanShadow_Evaluate(&state, &probe, 100U) == CAN_SHADOW_PROBE_READY);
    assert(CanShadow_Evaluate(&state, &check, 600U) ==
           CAN_SHADOW_VALUE_OK_NO_ACTION);
    assert(CanShadow_Evaluate(&state, &check, 601U) ==
           CAN_SHADOW_REJECT_SEQUENCE);
    probe.sequence = 12U;
    assert(CanShadow_Evaluate(&state, &probe, 700U) == CAN_SHADOW_PROBE_READY);
    check.sequence = 13U;
    check.test_value = 1001U;
    assert(CanShadow_Evaluate(&state, &check, 701U) ==
           CAN_SHADOW_REJECT_RANGE);
    check.test_value = 0U;
    assert(CanShadow_Evaluate(&state, &check, 702U) ==
           CAN_SHADOW_REJECT_RANGE);
    check.test_value = 1U;
    assert(CanShadow_Evaluate(&state, &check, 703U) ==
           CAN_SHADOW_VALUE_OK_NO_ACTION);
}

static void test_timeout_and_stop(void)
{
    CanShadow_State state;
    CanShadow_Request probe = {CAN_SHADOW_PROBE, 100U, 0U};
    CanShadow_Request check = {CAN_SHADOW_CHECK_VALUE, 101U, 1U};
    CanShadow_Request stop = {CAN_SHADOW_STOP_TEST, 0U, 0U};
    CanShadow_Reset(&state);
    assert(CanShadow_Evaluate(&state, &check, 0U) ==
           CAN_SHADOW_REJECT_NO_PROBE);
    assert(CanShadow_Evaluate(&state, &probe, 1000U) ==
           CAN_SHADOW_PROBE_READY);
    assert(CanShadow_Tick(&state, 1500U) == 0U);
    assert(CanShadow_Tick(&state, 1501U) == 1U);
    assert(CanShadow_Tick(&state, 1502U) == 0U);
    assert(CanShadow_Evaluate(&state, &check, 1502U) ==
           CAN_SHADOW_REJECT_TIMEOUT);
    assert(CanShadow_Evaluate(&state, &stop, 1503U) ==
           CAN_SHADOW_STOP_OBSERVED_NO_ACTION);
    assert(CanShadow_Evaluate(&state, &stop, 1504U) ==
           CAN_SHADOW_STOP_OBSERVED_NO_ACTION);
    assert(CanShadow_Evaluate(&state, &check, 1505U) ==
           CAN_SHADOW_REJECT_NO_PROBE);
}

static void test_wrap_and_bad_opcode(void)
{
    CanShadow_State state;
    CanShadow_Request probe = {CAN_SHADOW_PROBE, 0xFFFFU, 0U};
    CanShadow_Request check = {CAN_SHADOW_CHECK_VALUE, 0U, 1U};
    CanShadow_Reset(&state);
    assert(CanShadow_Evaluate(&state, &probe, 0U) == CAN_SHADOW_PROBE_READY);
    assert(CanShadow_Evaluate(&state, &check, 1U) ==
           CAN_SHADOW_VALUE_OK_NO_ACTION);
    probe.opcode = 99U;
    probe.sequence = 1U;
    assert(CanShadow_Evaluate(&state, &probe, 2U) ==
           CAN_SHADOW_REJECT_OPCODE);
}

int main(void)
{
    test_frames();
    test_probe_and_bounds();
    test_timeout_and_stop();
    test_wrap_and_bad_opcode();
    puts("can_shadow_diag_test: OK");
    return 0;
}
