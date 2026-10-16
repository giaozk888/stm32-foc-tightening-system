#include <math.h>
#include <stdint.h>
#include <stdio.h>

#include "as5047p_protocol.h"

static int failures = 0;
static int checks = 0;

#define CHECK_EQ(actual, expected) do { \
    long long a_ = (long long)(actual); \
    long long e_ = (long long)(expected); \
    ++checks; \
    if (a_ != e_) { \
        fprintf(stderr, "%s:%d: %s = %lld, expected %lld\n", \
                __FILE__, __LINE__, #actual, a_, e_); \
        ++failures; \
    } \
} while (0)

#define CHECK_NEAR(actual, expected, tolerance) do { \
    double a_ = (double)(actual); \
    double e_ = (double)(expected); \
    ++checks; \
    if (fabs(a_ - e_) > (tolerance)) { \
        fprintf(stderr, "%s:%d: %s = %.9f, expected %.9f\n", \
                __FILE__, __LINE__, #actual, a_, e_); \
        ++failures; \
    } \
} while (0)

static uint16_t even_response(uint16_t payload_and_ef)
{
    uint16_t frame = (uint16_t)(payload_and_ef & 0x7FFFU);
    if (AS5047P_ParityIsOdd(frame) != 0U)
    {
        frame |= 0x8000U;
    }
    return frame;
}

static void test_command_and_parity(void)
{
    CHECK_EQ(AS5047P_MakeReadCommand(0x0000U), 0xC000U);
    CHECK_EQ(AS5047P_MakeReadCommand(0x0001U), 0x4001U);
    CHECK_EQ(AS5047P_MakeReadCommand(0x3FFFU), 0xFFFFU);
    CHECK_EQ(AS5047P_MakeReadCommand(0xFFFFU), 0xFFFFU);

    for (uint32_t reg = 0U; reg < 16384U; ++reg)
    {
        uint16_t cmd = AS5047P_MakeReadCommand((uint16_t)reg);
        CHECK_EQ(cmd & 0x4000U, 0x4000U);
        CHECK_EQ(cmd & 0x3FFFU, reg);
        CHECK_EQ(AS5047P_ParityIsOdd(cmd), 0U);
    }

    for (uint32_t payload = 0U; payload < 32768U; ++payload)
    {
        uint16_t good = even_response((uint16_t)payload);
        CHECK_EQ(AS5047P_ParityIsOdd(good), 0U);
        CHECK_EQ(AS5047P_ParityIsOdd((uint16_t)(good ^ 0x0001U)), 1U);
        CHECK_EQ(AS5047P_ParityIsOdd((uint16_t)(good ^ 0x8000U)), 1U);
    }
}

static void test_response_and_error_decision(void)
{
    uint16_t angle = even_response(0x1234U);
    uint16_t ef = even_response(0x4000U | 0x1234U);
    uint16_t errfl = even_response(0x0005U);

    CHECK_EQ(AS5047P_ParityIsOdd(angle), 0U);
    CHECK_EQ(angle & 0x3FFFU, 0x1234U);
    CHECK_EQ(AS5047P_AngleFrameAction(angle, 0U), AS5047P_ANGLE_ACCEPT);
    CHECK_EQ(AS5047P_AngleFrameAction(ef, 0U), AS5047P_ANGLE_CLEAR_ERRFL);
    CHECK_EQ(AS5047P_AngleFrameAction(angle, 1U), AS5047P_ANGLE_ACCEPT);
    CHECK_EQ(AS5047P_AngleFrameAction(ef, 1U), AS5047P_ANGLE_FAIL);
    CHECK_EQ(AS5047P_ErrorFlags(errfl), 0x0005U);
    CHECK_EQ(AS5047P_ErrorFlags(even_response(0x4007U)), 0x0007U);
    CHECK_EQ(AS5047P_ParityIsOdd((uint16_t)(angle ^ 0x0040U)), 1U);
}

static void test_wrap_speed_and_electrical_angle(void)
{
    const uint16_t zero = 10507U;
    const float one_count_electrical =
        6.28318530717958647692f * 10.0f / 16384.0f;

    CHECK_EQ(AS5047P_Delta14(0U, 16383U), 1);
    CHECK_EQ(AS5047P_Delta14(16383U, 0U), -1);
    CHECK_EQ(AS5047P_Delta14(8192U, 0U), -8192);
    CHECK_EQ(AS5047P_Delta14(0U, 8192U), -8192);
    CHECK_EQ(AS5047P_Delta14(8193U, 0U), -8191);
    CHECK_EQ(AS5047P_Delta14(0U, 8193U), 8191);
    CHECK_EQ(AS5047P_Delta14(zero, zero), 0);

    /* The project's ENCODER_DIRECTION=-1 makes decreasing raw positive. */
    CHECK_NEAR(AS5047P_InstantRpm(-1, -1, 0.001f), 3.662109375, 0.0001);
    CHECK_NEAR(AS5047P_InstantRpm(1, -1, 0.001f), -3.662109375, 0.0001);
    CHECK_NEAR(AS5047P_InstantRpm(0, -1, 0.001f), 0.0, 0.0001);
    CHECK_NEAR(AS5047P_ElectricalAngleRad(zero, zero, 10U, -1), 0.0, 0.00001);
    CHECK_NEAR(AS5047P_ElectricalAngleRad((uint16_t)(zero - 1U), zero,
                                           10U, -1), one_count_electrical,
               0.00001);
    CHECK_NEAR(AS5047P_ElectricalAngleRad((uint16_t)(zero + 1U), zero,
                                           10U, -1),
               6.28318530717958647692 - one_count_electrical, 0.00001);
    CHECK_NEAR(AS5047P_ElectricalAngleRad(0U, 16383U, 10U, -1),
               6.28318530717958647692 - one_count_electrical, 0.00001);
}

int main(void)
{
    test_command_and_parity();
    test_response_and_error_decision();
    test_wrap_speed_and_electrical_angle();

    if (failures != 0)
    {
        fprintf(stderr, "AS5047P host tests FAILED: %d / %d checks\n",
                failures, checks);
        return 1;
    }
    printf("AS5047P host tests PASS: %d checks\n", checks);
    return 0;
}
