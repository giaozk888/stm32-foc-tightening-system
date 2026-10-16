#include <stdint.h>
#include <stdio.h>

#include "as5047p_transaction.h"

typedef struct
{
    uint16_t expected_tx;
    uint16_t rx;
    int status;
} Step;

typedef struct
{
    const Step *steps;
    unsigned length;
    unsigned used;
    unsigned mismatches;
} FakeDevice;

static int checks = 0;
static int failures = 0;

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

static uint16_t even_response(uint16_t low15)
{
    uint16_t response = (uint16_t)(low15 & 0x7FFFU);
    if (AS5047P_ParityIsOdd(response) != 0U)
    {
        response |= 0x8000U;
    }
    return response;
}

static int fake_exchange(void *context, uint16_t tx, uint16_t *rx)
{
    FakeDevice *device = (FakeDevice *)context;
    const Step *step;
    if (device->used >= device->length)
    {
        device->mismatches++;
        return 9;
    }
    step = &device->steps[device->used++];
    if (tx != step->expected_tx) { device->mismatches++; }
    *rx = step->rx;
    return step->status;
}

static void test_normal_two_frame_angle(void)
{
    const Step steps[] = {
        {0xFFFFU, 0x0001U, 0}, /* pipelined dummy: parity is ignored */
        {0xC000U, even_response(0x1234U), 0}
    };
    FakeDevice device = {steps, 2U, 0U, 0U};
    AS5047P_TransactionTrace_t trace = {0};
    uint16_t raw = 0xBEEFU;
    int status = AS5047P_ReadAngleVia(fake_exchange, &device, &raw, &trace);

    CHECK_EQ(status, 0);
    CHECK_EQ(raw, 0x1234U);
    CHECK_EQ(device.used, 2U);
    CHECK_EQ(device.mismatches, 0U);
    CHECK_EQ(trace.recovery_attempted, 0U);
    CHECK_EQ(trace.failure, AS5047P_TXN_NONE);
}

static void test_ef_errfl_retry_success(void)
{
    const Step steps[] = {
        {0xFFFFU, 0U, 0}, {0xC000U, even_response(0x4002U), 0},
        {0x4001U, 0U, 0}, {0xC000U, even_response(0x0005U), 0},
        {0xFFFFU, 0U, 0}, {0xC000U, even_response(0x2ABCU), 0}
    };
    FakeDevice device = {steps, 6U, 0U, 0U};
    AS5047P_TransactionTrace_t trace = {0};
    uint16_t raw = 0xBEEFU;
    int status = AS5047P_ReadAngleVia(fake_exchange, &device, &raw, &trace);

    CHECK_EQ(status, 0);
    CHECK_EQ(raw, 0x2ABCU);
    CHECK_EQ(device.used, 6U);
    CHECK_EQ(device.mismatches, 0U);
    CHECK_EQ(trace.first_angle_response, even_response(0x4002U));
    CHECK_EQ(trace.errfl, 0x0005U);
    CHECK_EQ(trace.errfl_valid, 1U);
    CHECK_EQ(trace.recovery_attempted, 1U);
    CHECK_EQ(trace.recovered, 1U);
    CHECK_EQ(trace.phase, AS5047P_PHASE_ANGLE_RETRY);
}

static void test_ef_persistent_rejected(void)
{
    const Step steps[] = {
        {0xFFFFU, 0U, 0}, {0xC000U, even_response(0x4001U), 0},
        {0x4001U, 0U, 0}, {0xC000U, even_response(0x0001U), 0},
        {0xFFFFU, 0U, 0}, {0xC000U, even_response(0x4003U), 0}
    };
    FakeDevice device = {steps, 6U, 0U, 0U};
    AS5047P_TransactionTrace_t trace = {0};
    uint16_t raw = 0xBEEFU;
    int status = AS5047P_ReadAngleVia(fake_exchange, &device, &raw, &trace);

    CHECK_EQ(status, 1);
    CHECK_EQ(raw, 0xBEEFU);
    CHECK_EQ(device.used, 6U);
    CHECK_EQ(device.mismatches, 0U);
    CHECK_EQ(trace.failure, AS5047P_TXN_EF_PERSISTENT);
    CHECK_EQ(trace.recovered, 0U);
}

static void test_transport_and_parity_failures(void)
{
    const Step first_fail[] = {{0xFFFFU, 0U, 2}};
    const Step second_fail[] = {
        {0xFFFFU, 0U, 0}, {0xC000U, 0U, 3}
    };
    const Step parity_fail[] = {
        {0xFFFFU, 0U, 0},
        {0xC000U, (uint16_t)(even_response(0x1234U) ^ 0x0001U), 0}
    };
    FakeDevice devices[] = {
        {first_fail, 1U, 0U, 0U},
        {second_fail, 2U, 0U, 0U},
        {parity_fail, 2U, 0U, 0U}
    };
    const int statuses[] = {2, 3, 1};
    const int stages[] = {
        AS5047P_TXN_FRAME1, AS5047P_TXN_FRAME2, AS5047P_TXN_PARITY
    };

    for (unsigned i = 0U; i < 3U; ++i)
    {
        AS5047P_TransactionTrace_t trace = {0};
        uint16_t raw = 0xBEEFU;
        int status = AS5047P_ReadAngleVia(fake_exchange, &devices[i],
                                           &raw, &trace);
        CHECK_EQ(status, statuses[i]);
        CHECK_EQ(trace.failure, stages[i]);
        CHECK_EQ(raw, 0xBEEFU);
        CHECK_EQ(devices[i].used, devices[i].length);
        CHECK_EQ(devices[i].mismatches, 0U);
    }
}

static void test_errfl_and_retry_failures(void)
{
    const Step errfl_fail[] = {
        {0xFFFFU, 0U, 0}, {0xC000U, even_response(0x4001U), 0},
        {0x4001U, 0U, 3}
    };
    const Step retry_fail[] = {
        {0xFFFFU, 0U, 0}, {0xC000U, even_response(0x4001U), 0},
        {0x4001U, 0U, 0}, {0xC000U, even_response(0x0002U), 0},
        {0xFFFFU, 0U, 0}, {0xC000U, 0U, 2}
    };
    FakeDevice errfl_device = {errfl_fail, 3U, 0U, 0U};
    FakeDevice retry_device = {retry_fail, 6U, 0U, 0U};
    AS5047P_TransactionTrace_t trace = {0};
    uint16_t raw = 0xBEEFU;

    CHECK_EQ(AS5047P_ReadAngleVia(fake_exchange, &errfl_device,
                                    &raw, &trace), 1);
    CHECK_EQ(trace.phase, AS5047P_PHASE_ERRFL);
    CHECK_EQ(trace.failure, AS5047P_TXN_FRAME1);
    CHECK_EQ(trace.errfl_valid, 0U);
    CHECK_EQ(raw, 0xBEEFU);
    CHECK_EQ(errfl_device.used, 3U);
    CHECK_EQ(errfl_device.mismatches, 0U);

    CHECK_EQ(AS5047P_ReadAngleVia(fake_exchange, &retry_device,
                                    &raw, &trace), 2);
    CHECK_EQ(trace.phase, AS5047P_PHASE_ANGLE_RETRY);
    CHECK_EQ(trace.failure, AS5047P_TXN_FRAME2);
    CHECK_EQ(trace.errfl, 0x0002U);
    CHECK_EQ(trace.errfl_valid, 1U);
    CHECK_EQ(raw, 0xBEEFU);
    CHECK_EQ(retry_device.used, 6U);
    CHECK_EQ(retry_device.mismatches, 0U);
}

int main(void)
{
    test_normal_two_frame_angle();
    test_ef_errfl_retry_success();
    test_ef_persistent_rejected();
    test_transport_and_parity_failures();
    test_errfl_and_retry_failures();

    if (failures != 0)
    {
        fprintf(stderr, "AS5047P transaction tests FAILED: %d / %d checks\n",
                failures, checks);
        return 1;
    }
    printf("AS5047P transaction tests PASS: %d checks\n", checks);
    return 0;
}
