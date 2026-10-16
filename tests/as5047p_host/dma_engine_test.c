#include "as5047p_dma_engine.h"
#include "as5047p_protocol.h"
#include <stdio.h>
#include <string.h>

static unsigned checks, failures, scenarios;
#define CHECK(a, b) do { \
    long long av = (long long)(a), bv = (long long)(b); ++checks; \
    if (av != bv) { ++failures; fprintf(stderr, "line %u: %s=%lld expected %lld\n", \
        __LINE__, #a, av, bv); } \
} while (0)
typedef struct {
    AsDmaEngine engine;
    uint32_t now, cs_time, start_time, guard, deadline;
    uint16_t words[8], responses[8];
    volatile uint16_t *tx, *rx;
    unsigned starts, stops, finished;
    unsigned snapshots, snapshot_stops;
    AsDmaStatus snapshot_status;
    AsDmaState snapshot_phase;
    uint32_t snapshot_frame, snapshot_now, snapshot_started;
    int high, busy, start_fail, no_rx, deadline_enabled;
    AsDmaStatus result;
} Fake;

static uint16_t Even(uint16_t value)
{
    value &= 0x7FFFU;
    return value | (AS5047P_ParityIsOdd(value) ? 0x8000U : 0U);
}
static void Cs(void *p, int high)
{
    Fake *f = p;
    if (high != f->high) { f->high = high; f->cs_time = f->now; }
}
static void Guard(void *p, uint32_t due) { ((Fake *)p)->guard = due; }
static void Deadline(void *p, int enabled, uint32_t due)
{
    Fake *f = p; f->deadline = due; f->deadline_enabled = enabled;
}
static int Start(void *p, volatile uint16_t *tx, volatile uint16_t *rx)
{
    Fake *f = p;
    CHECK(f->high, 0);
    CHECK(f->now - f->cs_time >= AS_DMA_GUARD_US, 1);
    CHECK(tx == &f->engine.tx, 1); CHECK(rx == &f->engine.rx, 1);
    f->tx = tx; f->rx = rx; f->start_time = f->now;
    if (f->starts < 8U) f->words[f->starts] = *tx;
    ++f->starts;
    return !f->start_fail;
}
static void Stop(void *p) { ++((Fake *)p)->stops; }
static int Busy(void *p) { return ((Fake *)p)->busy; }
static void Finish(void *p, AsDmaStatus status)
{
    Fake *f = p; ++f->finished; f->result = status;
}
static void FaultSnapshot(void *p, const AsDmaEngine *e,
                          AsDmaStatus status, uint32_t now)
{
    Fake *f = p;
    ++f->snapshots;
    f->snapshot_stops = f->stops;
    f->snapshot_status = status;
    f->snapshot_phase = e->state;
    f->snapshot_frame = e->frame;
    f->snapshot_now = now;
    f->snapshot_started = e->started_us;
}
static const AsDmaOps ops = {
    Cs, Guard, Deadline, Start, Stop, Busy, Finish, FaultSnapshot
};
static void Init(Fake *f, uint32_t now)
{
    memset(f, 0, sizeof(*f)); f->now = now; f->high = 1;
    f->responses[0] = 1U; /* invalid dummy parity must be ignored */
    f->responses[1] = Even(1234U);
    f->responses[3] = Even(3U);
    f->responses[5] = Even(2345U);
#if defined(AS_DMA_TEST_FIXED_OPS)
    (void)ops;
    AsDma_Init(&f->engine, NULL, f);
#else
    AsDma_Init(&f->engine, &ops, f);
#endif
    ++scenarios;
}
static void Begin(Fake *f, uint16_t reg)
{
    CHECK(AsDma_Begin(&f->engine, reg, f->now), 1);
    CHECK(f->engine.deadline_us - f->now, AS_DMA_TRANSACTION_US);
    CHECK(f->deadline_enabled, 1);
}
static void Drive(Fake *f)
{
    uint32_t expected_sequence = f->engine.sample.sequence + 1U;
    /* This is simulation time, not a target WCET or actual hardware timing. */
    for (unsigned tick = 0; tick < 300U && f->engine.state != AS_DMA_IDLE; ++tick) {
        ++f->now;
        AsDma_CheckDeadline(&f->engine, f->now);
        if (f->engine.state == AS_DMA_WORD && !f->no_rx &&
            f->now - f->start_time >= 4U) {
            *f->rx = f->responses[f->starts - 1U];
            AsDma_RxComplete(&f->engine, f->now);
        }
        AsDma_Guard(&f->engine, f->now);
    }
    CHECK(f->engine.state, AS_DMA_IDLE); CHECK(f->finished, 1U);
    CHECK(f->high, 1); CHECK(f->deadline_enabled, 0);
    CHECK(f->engine.sample.sequence, expected_sequence);
}
static void Normal(void)
{
    Fake f; Init(&f, 100U); Begin(&f, 0x3FFFU);
    CHECK(AsDma_Begin(&f.engine, 1U, f.now), 0);
    AsDma_Guard(&f.engine, f.now); CHECK(f.starts, 0U);
    Drive(&f);
    CHECK(f.result, AS_DMA_OK); CHECK(f.starts, 2U);
    CHECK(f.snapshots, 0U);
    CHECK(f.words[0], 0xFFFFU); CHECK(f.words[1], 0xC000U);
    CHECK(f.engine.sample.raw, 1234U); CHECK(f.engine.successes, 1U);
    CHECK(f.engine.sample.elapsed_us < AS_DMA_TRANSACTION_US, 1);
    CHECK(f.engine.sample.sample_us, f.start_time + 4U);
    unsigned finished = f.finished;
    AsDma_RxComplete(&f.engine, f.now + 1000U);
    AsDma_Guard(&f.engine, f.now + 1000U);
    AsDma_CheckDeadline(&f.engine, f.now + 1000U);
    CHECK(f.finished, finished);
}
static void Recovery(void)
{
    Fake f; Init(&f, 0U); f.responses[1] = Even(0x4000U);
    Begin(&f, 0x3FFFU); Drive(&f);
    CHECK(f.result, AS_DMA_OK); CHECK(f.starts, 6U);
    const uint16_t expected[] = {0xFFFFU,0xC000U,0x4001U,0xC000U,0xFFFFU,0xC000U};
    for (unsigned i = 0; i < 6U; ++i) CHECK(f.words[i], expected[i]);
    CHECK(f.engine.sample.raw, 2345U); CHECK(f.engine.sample.errfl, 3U);
    CHECK(f.engine.sample.errfl_valid, 1); CHECK(f.engine.sample.recovered, 1);

    Init(&f, 0U); f.responses[1] = f.responses[5] = Even(0x4000U);
    Begin(&f, 0x3FFFU); Drive(&f);
    CHECK(f.result, AS_DMA_EF); CHECK(f.starts, 6U); CHECK(f.engine.sample.raw, 0U);
    CHECK(f.engine.failures, 1U);

    Init(&f, 0U); f.responses[1] = Even(0x4000U) ^ 0x8000U;
    Begin(&f, 0x3FFFU); Drive(&f);
    CHECK(f.result, AS_DMA_PARITY); CHECK(f.starts, 2U); /* parity before EF */

    Init(&f, 0U); f.responses[1] = Even(0x4000U);
    f.responses[3] ^= 0x8000U;
    Begin(&f, 0x3FFFU); Drive(&f);
    CHECK(f.result, AS_DMA_PARITY); CHECK(f.starts, 4U);

    Init(&f, 0U); f.responses[1] = Even(5U);
    Begin(&f, 1U); Drive(&f);
    CHECK(f.result, AS_DMA_OK); CHECK(f.words[0], 0x4001U);
    CHECK(f.engine.sample.response, Even(5U));
}
static void Faults(void)
{
    Fake f; Init(&f, 0U); f.start_fail = 1;
    Begin(&f, 0x3FFFU); Drive(&f); CHECK(f.result, AS_DMA_IO);
    Init(&f, 0U); f.no_rx = 1;
    Begin(&f, 0x3FFFU); Drive(&f); CHECK(f.result, AS_DMA_TIMEOUT);
    CHECK(f.engine.sample.elapsed_us, AS_DMA_TRANSACTION_US);
    Init(&f, 0U); f.busy = 1;
    Begin(&f, 0x3FFFU); Drive(&f); CHECK(f.result, AS_DMA_TIMEOUT);
    CHECK(f.starts, 1U); /* never start another word while BSY is stuck */
    Init(&f, 0U); Begin(&f, 0x3FFFU);
    f.now = 2U; AsDma_Guard(&f.engine, f.now);
    f.now = 4U; AsDma_Fail(&f.engine, AS_DMA_IO, f.now);
    CHECK(f.result, AS_DMA_IO); CHECK(f.high, 1); CHECK(f.engine.sample.raw, 0U);
    Init(&f, 0U); Begin(&f, 0x3FFFU);
    f.now = 1U; AsDma_Fail(&f.engine, AS_DMA_CANCELLED, f.now);
    CHECK(f.result, AS_DMA_CANCELLED); CHECK(f.engine.failures, 0U);
    CHECK(f.snapshots, 0U);
    /* New epoch does not inherit the failed response or recovery flags. */
    f.finished = 0; Begin(&f, 0x3FFFU); Drive(&f);
    CHECK(f.result, AS_DMA_OK); CHECK(f.engine.sample.sequence, 2U);
}
static void Deadlines(void)
{
    for (int state = AS_DMA_SETUP; state <= AS_DMA_GAP; ++state) {
        Fake f; Init(&f, 0U); Begin(&f, 0x3FFFU);
        f.engine.state = (AsDmaState)state;
        f.now = AS_DMA_TRANSACTION_US - 1U;
        AsDma_CheckDeadline(&f.engine, f.now); CHECK(f.finished, 0U);
        ++f.now; AsDma_RxComplete(&f.engine, f.now);
        CHECK(f.result, AS_DMA_TIMEOUT); CHECK(f.finished, 1U);
        CHECK(f.snapshots, 1U); CHECK(f.snapshot_status, AS_DMA_TIMEOUT);
        CHECK(f.snapshot_phase, state); CHECK(f.snapshot_frame, 0U);
        CHECK(f.snapshot_now - f.snapshot_started, AS_DMA_TRANSACTION_US);
        CHECK(f.snapshot_stops, 0U); /* capture precedes DMA flag clear */
        CHECK(f.engine.sample.raw, 0U); CHECK(f.high, 1);
    }
    Fake f; Init(&f, 0xFFFFFFF0U); Begin(&f, 0x3FFFU); Drive(&f);
    CHECK(f.result, AS_DMA_OK); CHECK(f.engine.sample.elapsed_us < 200U, 1);
    Init(&f, 0xFFFFFFF0U); f.no_rx = 1; Begin(&f, 0x3FFFU); Drive(&f);
    CHECK(f.result, AS_DMA_TIMEOUT); CHECK(f.engine.sample.elapsed_us, 200U);
}
static void Consumer(void)
{
    ++scenarios;
    AsDmaCursor c = {0}; uint32_t dt = 9999U;
    AsDmaSample s = {.status=AS_DMA_PENDING};
    CHECK(AsDma_Consume(&c, &s, 100U, &dt), 0); CHECK(dt, 9999U);
    s = (AsDmaSample){.status=AS_DMA_OK, .sequence=1U, .sample_us=100U, .elapsed_us=20U};
    CHECK(AsDma_Consume(&c, &s, 120U, &dt), 1); CHECK(dt, 1000U);
    CHECK(AsDma_Consume(&c, &s, 200U, &dt), 0);
    CHECK(AsDma_Consume(&c, &s, 1601U, &dt), -1); /* duplicate cannot stay valid forever */
    s.sequence = 2U; s.sample_us = 1250U;
    CHECK(AsDma_Consume(&c, &s, 1400U, &dt), 1); CHECK(dt, 1150U);
    s.sequence = 3U; s.sample_us = 3250U;
    CHECK(AsDma_Consume(&c, &s, 3300U, &dt), 1); CHECK(dt, 2000U); /* actual missed-period time */
    s.sequence = 4U; s.sample_us = 6250U;
    CHECK(AsDma_Consume(&c, &s, 6300U, &dt), -1);
    s.sample_us = 3250U; CHECK(AsDma_Consume(&c, &s, 3300U, &dt), -1); /* zero interval */
    s.status = AS_DMA_PARITY; CHECK(AsDma_Consume(&c, &s, 3300U, &dt), -1);
    s.status = AS_DMA_OK; s.elapsed_us = 200U;
    CHECK(AsDma_Consume(&c, &s, 3300U, &dt), -1);
    c = (AsDmaCursor){.valid=1U,.sequence=0xFFFFFFFFU,.sample_us=0xFFFFFF00U};
    s = (AsDmaSample){.status=AS_DMA_OK,.sequence=0U,.sample_us=0x00000300U,.elapsed_us=20U};
    CHECK(AsDma_Consume(&c, &s, 0x310U, &dt), 1); CHECK(dt, 1024U);
}
static void FinalGuardDelay(void)
{
    /* Reproduce the board's completed-DMA/final-HOLD fault without changing
     * the 200 us contract. Service before the deadline succeeds; at the
     * deadline it fails even though the response is already in memory. */
    for (unsigned late = 0U; late < 2U; ++late) {
        Fake f; Init(&f, 0U); Begin(&f, 0x3FFFU);
        for (unsigned tick = 0U; tick < 100U; ++tick) {
            ++f.now;
            if (f.engine.state == AS_DMA_WORD && f.now - f.start_time >= 4U) {
                *f.rx = f.responses[f.starts - 1U];
                AsDma_RxComplete(&f.engine, f.now);
            }
            if (f.engine.state == AS_DMA_HOLD && f.engine.frame == 1U) break;
            AsDma_Guard(&f.engine, f.now);
        }
        CHECK(f.engine.state, AS_DMA_HOLD); CHECK(f.engine.frame, 1U);
        CHECK(f.starts, 2U);
        f.now = AS_DMA_TRANSACTION_US - 1U + late;
        AsDma_Guard(&f.engine, f.now);
        CHECK(f.result, late ? AS_DMA_TIMEOUT : AS_DMA_OK);
        CHECK(f.finished, 1U); CHECK(f.high, 1);
        CHECK(f.snapshots, late);
        CHECK(f.engine.sample.raw, late ? 0U : 1234U);
        if (late) CHECK(f.snapshot_phase, AS_DMA_HOLD);
    }
}
int main(void)
{
    Normal(); Recovery(); Faults(); Deadlines(); Consumer(); FinalGuardDelay();
    printf("DMA FSM: %u scenarios, %u checks, %u failures (simulated, not hardware WCET)\n",
           scenarios, checks, failures);
    return failures ? 1 : 0;
}
