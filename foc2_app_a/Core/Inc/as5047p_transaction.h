#ifndef AS5047P_TRANSACTION_H
#define AS5047P_TRANSACTION_H

#include <stdint.h>

#include "as5047p_protocol.h"

/* Transport returns 0 on success; nonzero values are propagated except
 * ERRFL read failures, which are reported as the generic error 1. */
typedef int (*AS5047P_Exchange16Fn)(void *context, uint16_t tx, uint16_t *rx);

typedef enum
{
    AS5047P_TXN_NONE = 0,
    AS5047P_TXN_FRAME1 = 1,
    AS5047P_TXN_FRAME2 = 2,
    AS5047P_TXN_PARITY = 3,
    AS5047P_TXN_EF_PERSISTENT = 4
} AS5047P_TransactionFailure_t;

typedef enum
{
    AS5047P_PHASE_REGISTER = 0,
    AS5047P_PHASE_ANGLE_FIRST = 1,
    AS5047P_PHASE_ERRFL = 2,
    AS5047P_PHASE_ANGLE_RETRY = 3
} AS5047P_TransactionPhase_t;

typedef struct
{
    AS5047P_TransactionFailure_t failure;
    AS5047P_TransactionPhase_t phase;
    uint16_t reg;
    uint16_t command;
    uint16_t dummy;
    uint16_t response;
    uint16_t first_angle_response;
    uint16_t errfl;
    uint8_t recovery_attempted;
    uint8_t errfl_valid;
    uint8_t recovered;
    int transport_status;
} AS5047P_TransactionTrace_t;

static inline int AS5047P_ReadRegisterVia(AS5047P_Exchange16Fn exchange,
                                           void *context, uint16_t reg,
                                           uint16_t *response,
                                           AS5047P_TransactionTrace_t *trace)
{
    AS5047P_TransactionTrace_t local = {0};
    uint16_t dummy = 0U;
    uint16_t value = 0U;
    uint16_t command = AS5047P_MakeReadCommand(reg);
    int status;

    if (trace == 0) { trace = &local; }
    trace->failure = AS5047P_TXN_NONE;
    trace->reg = reg;
    trace->command = command;

    status = exchange(context, command, &dummy);
    trace->dummy = dummy;
    if (status != 0)
    {
        trace->failure = AS5047P_TXN_FRAME1;
        trace->transport_status = status;
        return status;
    }

    status = exchange(context, AS5047P_MakeReadCommand(0U), &value);
    trace->response = value;
    if (status != 0)
    {
        trace->failure = AS5047P_TXN_FRAME2;
        trace->transport_status = status;
        return status;
    }
    if (AS5047P_ParityIsOdd(value) != 0U)
    {
        trace->failure = AS5047P_TXN_PARITY;
        return 1;
    }
    if (response != 0) { *response = value; }
    return 0;
}

static inline int AS5047P_ReadAngleVia(AS5047P_Exchange16Fn exchange,
                                        void *context, uint16_t *raw,
                                        AS5047P_TransactionTrace_t *trace)
{
    AS5047P_TransactionTrace_t local = {0};
    uint16_t response = 0U;
    uint16_t errfl_response = 0U;
    int status;

    if (trace == 0) { trace = &local; }
    *trace = (AS5047P_TransactionTrace_t){0};
    trace->phase = AS5047P_PHASE_ANGLE_FIRST;
    status = AS5047P_ReadRegisterVia(exchange, context, 0x3FFFU,
                                      &response, trace);
    if (status != 0) { return status; }
    trace->first_angle_response = response;

    if (AS5047P_AngleFrameAction(response, 0U) ==
        AS5047P_ANGLE_CLEAR_ERRFL)
    {
        trace->recovery_attempted = 1U;
        trace->phase = AS5047P_PHASE_ERRFL;
        status = AS5047P_ReadRegisterVia(exchange, context, 0x0001U,
                                          &errfl_response, trace);
        if (status != 0) { return 1; }
        trace->errfl = AS5047P_ErrorFlags(errfl_response);
        trace->errfl_valid = 1U;

        trace->phase = AS5047P_PHASE_ANGLE_RETRY;
        status = AS5047P_ReadRegisterVia(exchange, context, 0x3FFFU,
                                          &response, trace);
        if (status != 0) { return status; }
        if (AS5047P_AngleFrameAction(response, 1U) == AS5047P_ANGLE_FAIL)
        {
            trace->failure = AS5047P_TXN_EF_PERSISTENT;
            return 1;
        }
        trace->recovered = 1U;
    }

    if (raw != 0) { *raw = (uint16_t)(response & 0x3FFFU); }
    return 0;
}

#endif /* AS5047P_TRANSACTION_H */
