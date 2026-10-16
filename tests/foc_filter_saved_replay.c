/* Read saved OFF raw pairs on stdin; never connects to hardware. */
#include <inttypes.h>
#include <math.h>
#include <stdio.h>
#include "foc_current_trend4.h"
#include "foc_filtered_protection_candidate.h"
typedef struct {
    uint32_t pairs, outside100, hit[3], changed, changed_u, changed_v;
    uint16_t low[2], high[2];
} Stats;
static void push(Stats *s,uint16_t u,uint16_t v,uint16_t original_u,uint16_t original_v)
{
    uint16_t x[2]={u,v};
    if (!s->pairs) { s->low[0]=s->high[0]=u; s->low[1]=s->high[1]=v; }
    for (unsigned c=0;c<2;++c) {
        if (x[c]<s->low[c]) s->low[c]=x[c];
        if (x[c]>s->high[c]) s->high[c]=x[c];
    }
    ++s->pairs;
    if (FocTrend4_Distance(u,1560)>100U || FocTrend4_Distance(v,1560)>100U) ++s->outside100;
    float a=((int32_t)1560-u)*(3.3f/4095.0f/0.12f);
    float b=((int32_t)1560-v)*(3.3f/4095.0f/0.12f);
    uint8_t mask=FocOcConfirm_Mask(a,b,-(a+b),4.0f,0);
    for (unsigned c=0;c<3;++c) s->hit[c]+=(mask>>c)&1U;
    s->changed_u+=(u!=original_u); s->changed_v+=(v!=original_v);
    s->changed+=(u!=original_u || v!=original_v);
}
static uint16_t median(uint16_t a,uint16_t b,uint16_t c)
{ if (a>b) { uint16_t t=a;a=b;b=t; } if (b>c) { uint16_t t=b;b=c;c=t; } return a>b?a:b; }
static void print_stats(const char *name,const Stats *s)
{
    printf("\"%s\":{\"pairs\":%"PRIu32",\"outside100\":%"PRIu32
           ",\"hit4A\":[%"PRIu32",%"PRIu32",%"PRIu32"],\"changed_pairs\":%"PRIu32
           ",\"changed_uv\":[%"PRIu32",%"PRIu32"],\"range_uv\":[[%u,%u],[%u,%u]]}",
           name,s->pairs,s->outside100,s->hit[0],s->hit[1],s->hit[2],s->changed,
           s->changed_u,s->changed_v,s->low[0],s->high[0],s->low[1],s->high[1]);
}
int main(void)
{
    uint16_t h[4][2]={{0}};
    unsigned u,v;
    uint32_t n=0U,first_trip=UINT32_MAX;
    Stats raw={0},med={0},trend={0};
    FocFilteredProtection policy;
    /* OFFLINE test values, not motor settings. */
    FocFp_Begin(&policy,(FocFilteredProtectionConfig){4,100,100,3,2},0);
    while (scanf("%u %u",&u,&v)==2) {
        if (u>4095U || v>4095U) return 2;
        for (unsigned j=0;j<3;++j) {h[j][0]=h[j+1][0];h[j][1]=h[j+1][1];}
        h[3][0]=(uint16_t)u;h[3][1]=(uint16_t)v;
        uint16_t tu=0,tv=0;
        uint8_t mask=0;
        if (n>=3U) {
            tu=FocTrend4_Select(h[0][0],h[1][0],h[2][0],h[3][0]);
            tv=FocTrend4_Select(h[0][1],h[1][1],h[2][1],h[3][1]);
            push(&raw,h[2][0],h[2][1],h[2][0],h[2][1]);
            push(&med,median(h[1][0],h[2][0],h[3][0]),median(h[1][1],h[2][1],h[3][1]),h[2][0],h[2][1]);
            push(&trend,tu,tv,h[2][0],h[2][1]);
            mask=(uint8_t)((tu!=h[2][0])|((tv!=h[2][1])<<1U));
        }
        FocFp_Push(&policy,n,n*50U,(uint16_t)u,(uint16_t)v,n>=3U,n-1U,
            ((int32_t)1560-tu)*(3.3f/4095.0f/0.12f),
            ((int32_t)1560-tv)*(3.3f/4095.0f/0.12f),mask,0);
        if (policy.result==FOC_OC_TRIPPED && first_trip==UINT32_MAX) first_trip=n;
        ++n;
    }
    if (n<4U || !feof(stdin)) return 3;
    printf("{\"source_pairs\":%"PRIu32",\"aligned_centers\":\"2..N-2\",",n);
    print_stats("raw",&raw);printf(",");print_stats("median3",&med);printf(",");print_stats("trend4",&trend);
    printf(",\"offline_candidate\":{\"result\":%u,\"reason\":%u,\"first_trip_physical_index\":",
        (unsigned)policy.result,(unsigned)policy.reason);
    if (first_trip==UINT32_MAX) printf("null"); else printf("%"PRIu32,first_trip);
    printf("},\"bridge_switch_test\":false,\"motor_qualified\":false}\n");
    return 0;
}
