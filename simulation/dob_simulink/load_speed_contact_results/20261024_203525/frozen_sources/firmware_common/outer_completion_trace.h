#ifndef OUTER_COMPLETION_TRACE_H
#define OUTER_COMPLETION_TRACE_H
#include <stdint.h>
#define OUTER_TRACE_CAPACITY 16U
typedef struct {
    uint32_t entry_us,consume_us,sample_us,sequence,commit_us;
    uint32_t observe_begin_us,observe_end_us,status,phase;
} OuterCompletionFrame;
typedef struct {
    OuterCompletionFrame frames[OUTER_TRACE_CAPACITY],current;
    uint32_t head,count;
    volatile uint32_t frozen,fault_phase;
    uint32_t last_entry_us,max_entry_gap_us,max_core_us,max_observe_us;
} OuterCompletionTrace;
static inline void OuterTrace_Enter(OuterCompletionTrace *s,uint32_t now,uint8_t fault)
{
    if (s->frozen) return;
    if (fault) {s->frozen=1U;return;} /* Keep the exact in-flight phase. */
    if (s->count) {
        s->frames[s->head]=s->current;
        s->head=(s->head+1U)%OUTER_TRACE_CAPACITY;
        uint32_t gap=now-s->last_entry_us;
        if (gap>s->max_entry_gap_us) s->max_entry_gap_us=gap;
    }
    ++s->count;s->last_entry_us=now;
    s->current=(OuterCompletionFrame){.entry_us=now,.phase=1U};
}
static inline void OuterTrace_Consume(OuterCompletionTrace *s,uint32_t now,uint32_t sample,uint32_t seq)
{
    if (s->frozen) return;
    s->current.consume_us=now;s->current.sample_us=sample;s->current.sequence=seq;s->current.phase=2U;
}
static inline void OuterTrace_Commit(OuterCompletionTrace *s,uint32_t now)
{
    if (s->frozen) return;
    s->current.commit_us=now;s->current.phase=3U;
    uint32_t elapsed=now-s->current.entry_us;
    if (elapsed>s->max_core_us) s->max_core_us=elapsed;
}
static inline void OuterTrace_ObserveBegin(OuterCompletionTrace *s,uint32_t now)
{
    if (s->frozen) return;
    s->current.observe_begin_us=now;s->current.phase=4U;
}
static inline void OuterTrace_ObserveEnd(OuterCompletionTrace *s,uint32_t now)
{
    if (s->frozen) return;
    s->current.observe_end_us=now;s->current.phase=5U;
    uint32_t elapsed=now-s->current.observe_begin_us;
    if (elapsed>s->max_observe_us) s->max_observe_us=elapsed;
}
#endif
