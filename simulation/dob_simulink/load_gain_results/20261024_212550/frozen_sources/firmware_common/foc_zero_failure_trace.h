#ifndef FOC_ZERO_FAILURE_TRACE_H
#define FOC_ZERO_FAILURE_TRACE_H
#include "foc_zero_median.h"
#include "foc_current_spike.h"
#include <string.h>
/* Diagnostic-only ISR writer; read only after Freeze. Sequence is 1-based
 * physical ADC pair index. Each point labels the delayed CENTER, not arrival.
 * Fixed ring, no allocation/formatting/copy of the full ring in the ISR. */
enum { FOC_TRACE_CAPACITY=64, FOC_TRACE_PRE=32, FOC_TRACE_POST=16 };
typedef struct {
    uint32_t seq;
    uint16_t au,av,bu,bv,cu,cv,fu,fv;
    uint8_t mask;
} FocZeroTracePoint;
typedef struct {
    FocZeroTracePoint ring[FOC_TRACE_CAPACITY], extrema[4]; /* U min/max, V min/max */
    uint32_t physical, trigger, window_count, restarts, span_restarts, drift_restarts;
    uint16_t prior_u[2],prior_v[2], min_u,max_u,min_v,max_v;
    uint8_t write,count,post,triggered,done,reason,extrema_valid;
} FocZeroFailureTrace;
static inline void FocTrace_Begin(FocZeroFailureTrace *t) { memset(t,0,sizeof(*t)); }
static inline void FocTrace_Freeze(FocZeroFailureTrace *t) { t->done=1U; }
static inline FocZeroTracePoint FocTrace_Record(FocZeroFailureTrace *t,uint16_t u,uint16_t v)
{
    FocZeroTracePoint p={0};
    if (t->done) return p;
    ++t->physical;
    if (t->physical>=3U) {
        p.seq=t->physical-1U;
        p.au=t->prior_u[0]; p.av=t->prior_v[0];
        p.bu=t->prior_u[1]; p.bv=t->prior_v[1]; p.cu=u; p.cv=v;
        p.fu=FocSpike3_Select(p.au,p.bu,p.cu); p.fv=FocSpike3_Select(p.av,p.bv,p.cv);
        p.mask=(uint8_t)(FocSpike3_Isolated(p.au,p.bu,p.cu) |
                        (FocSpike3_Isolated(p.av,p.bv,p.cv)<<1U));
        t->ring[t->write]=p;
        t->write=(uint8_t)((t->write+1U)%FOC_TRACE_CAPACITY);
        if (t->count<FOC_TRACE_CAPACITY) ++t->count;
    }
    t->prior_u[0]=t->prior_u[1]; t->prior_u[1]=u;
    t->prior_v[0]=t->prior_v[1]; t->prior_v[1]=v;
    if (t->triggered && ++t->post>=FOC_TRACE_POST) FocTrace_Freeze(t);
    return p;
}
static inline void FocTrace_Push(FocZeroFailureTrace *t,FocZeroMedian *m,
                                FocZeroCal *c,uint16_t u,uint16_t v)
{
    if (t->done) return;
    FocZeroTracePoint p=FocTrace_Record(t,u,v);
    if (t->triggered) return; /* Post-failure raw ONLY; calibration remains latched. */
    uint32_t before_count=c->count;
    if (p.seq && c->state==FOC_ZERO_COLLECTING) {
        if (!before_count) {
            for (unsigned i=0;i<4U;++i) t->extrema[i]=p;
            t->extrema_valid=1U;
        } else {
            if (p.fu<t->extrema[0].fu) t->extrema[0]=p;
            if (p.fu>t->extrema[1].fu) t->extrema[1]=p;
            if (p.fv<t->extrema[2].fv) t->extrema[2]=p;
            if (p.fv>t->extrema[3].fv) t->extrema[3]=p;
        }
    }
    FocZeroMedian_Push(m,c,u,v); /* Original gates/filter, unchanged. */
    if (c->state==FOC_ZERO_FAILED) {
        t->triggered=1U; t->trigger=p.seq; t->reason=(uint8_t)c->reason;
        t->window_count=before_count; t->restarts=c->restarts;
        t->span_restarts=c->span_restarts; t->drift_restarts=c->drift_restarts;
        t->min_u=c->min_u; t->max_u=c->max_u; t->min_v=c->min_v; t->max_v=c->max_v;
        /* Invalid ADC codes never qualify for continued acquisition. */
        if (u>4095U || v>4095U || !p.seq) FocTrace_Freeze(t);
    } else if (c->state==FOC_ZERO_READY) FocTrace_Freeze(t);
}
static inline unsigned FocTrace_Rows(const FocZeroFailureTrace *t)
{
    if (!t->done) return 0U;
    unsigned n=0U;
    for (unsigned i=0;i<t->count;++i) {
        unsigned idx=(t->write+FOC_TRACE_CAPACITY-t->count+i)%FOC_TRACE_CAPACITY;
        uint32_t s=t->ring[idx].seq;
        if (!t->triggered || (s+FOC_TRACE_PRE>=t->trigger && s<=t->trigger+FOC_TRACE_POST)) ++n;
    }
    return n;
}
static inline int FocTrace_Read(const FocZeroFailureTrace *t,unsigned row,FocZeroTracePoint *p)
{
    if (!t->done) return 0;
    unsigned n=0U;
    for (unsigned i=0;i<t->count;++i) {
        unsigned idx=(t->write+FOC_TRACE_CAPACITY-t->count+i)%FOC_TRACE_CAPACITY;
        uint32_t s=t->ring[idx].seq;
        if (!t->triggered || (s+FOC_TRACE_PRE>=t->trigger && s<=t->trigger+FOC_TRACE_POST)) {
            if (n++==row) { *p=t->ring[idx]; return 1; }
        }
    }
    return 0;
}
#endif
