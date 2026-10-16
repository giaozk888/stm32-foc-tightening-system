#ifndef AS5047P_PROTOCOL_H
#define AS5047P_PROTOCOL_H

#include <math.h>
#include <stdint.h>

/* Pure protocol/math helpers shared by firmware and host tests. No HAL I/O. */
#define AS5047P_PROTOCOL_CPR 16384U

typedef enum
{
    AS5047P_ANGLE_ACCEPT = 0,
    AS5047P_ANGLE_CLEAR_ERRFL = 1,
    AS5047P_ANGLE_FAIL = 2
} AS5047P_AngleAction_t;

static inline uint8_t AS5047P_ParityIsOdd(uint16_t x)
{
    x ^= (uint16_t)(x >> 8);
    x ^= (uint16_t)(x >> 4);
    x ^= (uint16_t)(x >> 2);
    x ^= (uint16_t)(x >> 1);
    return (uint8_t)(x & 1U);
}

static inline uint16_t AS5047P_MakeReadCommand(uint16_t reg)
{
    uint16_t cmd = (uint16_t)((reg & 0x3FFFU) | 0x4000U);
    if (AS5047P_ParityIsOdd(cmd) != 0U)
    {
        cmd |= 0x8000U;
    }
    return cmd;
}

/* Caller checks response parity before interpreting EF or angle data. */
static inline AS5047P_AngleAction_t AS5047P_AngleFrameAction(
    uint16_t response, uint8_t after_errfl_clear)
{
    if ((response & 0x4000U) == 0U)
    {
        return AS5047P_ANGLE_ACCEPT;
    }
    return (after_errfl_clear != 0U) ? AS5047P_ANGLE_FAIL
                                     : AS5047P_ANGLE_CLEAR_ERRFL;
}

static inline uint16_t AS5047P_ErrorFlags(uint16_t response)
{
    return (uint16_t)(response & 0x0007U);
}

static inline int32_t AS5047P_Delta14(uint16_t newer, uint16_t older)
{
    int32_t delta = (int32_t)newer - (int32_t)older;
    if (delta > 8191)
    {
        delta -= (int32_t)AS5047P_PROTOCOL_CPR;
    }
    else if (delta < -8192)
    {
        delta += (int32_t)AS5047P_PROTOCOL_CPR;
    }
    return delta;
}

static inline float AS5047P_InstantRpm(int32_t delta, int direction,
                                        float elapsed_s)
{
    return ((float)direction * (float)delta * 60.0f) /
           ((float)AS5047P_PROTOCOL_CPR * elapsed_s);
}

static inline float AS5047P_ElectricalAngleRad(uint16_t raw,
                                                uint16_t zero_raw,
                                                uint32_t pole_pairs,
                                                int direction)
{
    const float two_pi = 6.28318530717958647692f;
    float theta = (float)direction *
                  (float)AS5047P_Delta14(raw, zero_raw) *
                  two_pi * (float)pole_pairs /
                  (float)AS5047P_PROTOCOL_CPR;
    theta = fmodf(theta, two_pi);
    if (theta < 0.0f)
    {
        theta += two_pi;
    }
    return theta;
}

#endif /* AS5047P_PROTOCOL_H */
