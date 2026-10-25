#ifndef CAN_WIRE_PROFILE_H
#define CAN_WIRE_PROFILE_H

#include <stdint.h>

/* Explicitly opt in; the existing production/classic profiles are unchanged. */
#ifndef CAN_WIRE_FD_ENABLED
#define CAN_WIRE_FD_ENABLED 0
#endif
#ifndef CAN_WIRE_BRS_ENABLED
#define CAN_WIRE_BRS_ENABLED 0
#endif
#ifndef CAN_WIRE_FD_ECHO_ONLY
#define CAN_WIRE_FD_ECHO_ONLY 0
#endif
#if CAN_WIRE_BRS_ENABLED && !CAN_WIRE_FD_ENABLED
#error "Bit-rate switching requires CAN FD"
#endif
#if CAN_WIRE_FD_ECHO_ONLY && !CAN_WIRE_FD_ENABLED
#error "The isolated echo-only gate requires CAN FD"
#endif

/* Echo fixture suppresses background status/log/RPC transmissions. */
static inline uint8_t CanWire_TxAllowed(uint32_t identifier, uint8_t echo_only) {
    return (uint8_t)(!echo_only || identifier == 0x703U);
}

#define CAN_WIRE_CLOCK_HZ 170000000U
#define CAN_WIRE_NOMINAL_PRESCALER 17U
#define CAN_WIRE_NOMINAL_SEG1 16U
#define CAN_WIRE_NOMINAL_SEG2 3U
/* 170 MHz / (5 * (1 + 12 + 4)) = 2 Mbit/s, sample point 76.47%. */
#define CAN_WIRE_DATA_PRESCALER 5U
#define CAN_WIRE_DATA_SEG1 12U
#define CAN_WIRE_DATA_SEG2 4U
#define CAN_WIRE_TDC_OFFSET (CAN_WIRE_DATA_PRESCALER * (1U + CAN_WIRE_DATA_SEG1))

/* This project's HAL returns an unshifted DLC code, NOT the byte count. */
static inline uint8_t CanWire_DlcBytes(uint32_t dlc) {
    static const uint8_t lengths[16] = {0, 1, 2, 3, 4, 5, 6, 7, 8, 12, 16, 20, 24, 32, 48, 64};
    return dlc < 16U ? lengths[dlc] : 0U;
}

static inline uint8_t CanWire_ModeMatches(uint8_t expected_fd, uint8_t actual_fd) {
    return (uint8_t)((expected_fd != 0U) == (actual_fd != 0U));
}

#endif
