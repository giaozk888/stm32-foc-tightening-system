#ifndef BRIDGE_FEEDBACK_FILTER_CORE_H
#define BRIDGE_FEEDBACK_FILTER_CORE_H
#include "foc_filtered_protection_candidate.h"
#include "foc_current_trend4.h"

/* Diagnostic only: no angle, PI, torque request, GPIO or motor admission. */
#define BRIDGE_FILTER_MAX_US 50000U
#define BRIDGE_FILTER_PAIRS 1000U
typedef struct {
    FocFilteredProtection protection;
    uint16_t history[4][2], zero_u, zero_v, selected_u, selected_v;
    float count_to_A;
    uint32_t pairs;
    uint8_t repair_mask;
} BridgeFeedbackFilter;

static inline int BridgeFilter_Begin(BridgeFeedbackFilter *s,
                                     uint16_t zu, uint16_t zv, uint32_t vdda_mv)
{
    *s=(BridgeFeedbackFilter){0};
    s->zero_u=zu; s->zero_v=zv;
    s->count_to_A=(float)vdda_mv/(4095.0f*120.0f);
    FocFilteredProtectionConfig cfg={4.0f,100U,100U,6U,4U};
    FocFp_Begin(&s->protection,cfg,0U);
    if (zu>4095U || zv>4095U || vdda_mv<3000U || vdda_mv>3600U)
        FocFp_Trip(&s->protection,FOC_FP_CONFIG,0U);
    return s->protection.result!=FOC_OC_TRIPPED;
}
static inline FocOcConfirmResult BridgeFilter_Push(
    BridgeFeedbackFilter *s, uint16_t u, uint16_t v, uint32_t now_us)
{
    if (s->protection.result==FOC_OC_TRIPPED) return s->protection.result;
    if (s->pairs>=BRIDGE_FILTER_PAIRS || now_us>=BRIDGE_FILTER_MAX_US)
        return FocFp_Trip(&s->protection,FOC_FP_TIMEOUT,0U);
    /* Catch a missed 50us pair, not just a stopped stream. */
    if (s->protection.seq_valid &&
        (uint32_t)(now_us-s->protection.last_us)>75U)
        return FocFp_Trip(&s->protection,FOC_FP_SEQUENCE,0U);
    uint32_t seq=++s->pairs;
    for (unsigned i=0U;i<3U;++i) {
        s->history[i][0]=s->history[i+1U][0];
        s->history[i][1]=s->history[i+1U][1];
    }
    s->history[3][0]=u; s->history[3][1]=v;
    uint8_t ready=seq>=4U;
    float iu=0.0f,iv=0.0f; s->repair_mask=0U;
    if (ready) {
        s->selected_u=FocTrend4_Select(s->history[0][0],s->history[1][0],s->history[2][0],u);
        s->selected_v=FocTrend4_Select(s->history[0][1],s->history[1][1],s->history[2][1],v);
        s->repair_mask=(s->selected_u!=s->history[2][0]?1U:0U)|
                       (s->selected_v!=s->history[2][1]?2U:0U);
        iu=((int32_t)s->zero_u-s->selected_u)*s->count_to_A;
        iv=((int32_t)s->zero_v-s->selected_v)*s->count_to_A;
    }
    return FocFp_Push(&s->protection,seq,now_us,u,v,ready,seq-1U,iu,iv,s->repair_mask,0U);
}
#endif
