#include <stdio.h>
#include <stdlib.h>
#include "foc_zero_failure_trace.h"
#define CHECK(x) do { if (!(x)) { fprintf(stderr,"line %d: %s\n",__LINE__,#x); exit(1); } } while(0)
static FocZeroFailureTrace t;
static FocZeroMedian m,plain_m;
static FocZeroCal c,plain_c;
static void begin(void) {
    FocTrace_Begin(&t); FocZeroMedian_Begin(&m,&c,1560);
    FocZeroMedian_Begin(&plain_m,&plain_c,1560);
}
static void push(uint16_t u,uint16_t v) {
    FocTrace_Push(&t,&m,&c,u,v);
    FocZeroMedian_Push(&plain_m,&plain_c,u,v);
    CHECK(memcmp(&c,&plain_c,sizeof(c))==0);
    CHECK(memcmp(&m,&plain_m,sizeof(m))==0);
}
int main(void) {
    begin();
    for (unsigned n=0;n<20002U;++n) push(1560,1560);
    for (unsigned trial=0;trial<8U && !t.triggered;++trial) {
        /* Two-sample plateaus intentionally survive either filter revision.
         * Stop exactly at failure, then exercise the explicit post phase. */
        for (unsigned n=0;n<406U && !t.triggered;++n) {
            uint16_t u=n<2U?1501U:(n>=203U && n<205U?1619U:1560U);
            push(u,1560);
        }
    }
    CHECK(c.state==FOC_ZERO_FAILED && c.reason==FOC_ZERO_UNSTABLE);
    CHECK(t.triggered && !t.done && t.post==0U && t.restarts==8U);
    CHECK(t.max_u-t.min_u==118U);
    CHECK(t.extrema[0].bu==1501U && t.extrema[0].mask==0U);
    CHECK(t.extrema[1].bu==1619U);
    CHECK(t.extrema[0].seq==t.trigger || t.extrema[1].seq==t.trigger);
    CHECK(t.extrema[0].seq+32U<t.trigger || t.extrema[1].seq+32U<t.trigger);
    FocZeroCal saved=c; uint32_t pairs=m.pairs;
    for (unsigned n=0;n<16U;++n) push(1560,1560);
    CHECK(t.done && t.post==16U && m.pairs==pairs);
    CHECK(memcmp(&saved,&c,sizeof(c))==0);
    CHECK(FocTrace_Rows(&t)==49U);
    for (unsigned n=0;n<49U;++n) {
        FocZeroTracePoint p;
        CHECK(FocTrace_Read(&t,n,&p));
        CHECK(p.seq==t.trigger-32U+n);
        CHECK(p.fu==FocSpike3_Select(p.au,p.bu,p.cu));
        CHECK(p.fv==FocSpike3_Select(p.av,p.bv,p.cv));
    }
    FocZeroTracePoint p; CHECK(!FocTrace_Read(&t,49U,&p));
    uint32_t physical=t.physical; push(3000,3000); CHECK(t.physical==physical);
    begin(); for (unsigned n=0;n<24002U;++n) push(1560,1560);
    CHECK(t.done && !t.triggered && c.state==FOC_ZERO_READY);
    begin(); push(1560,1560); push(1560,1560); push(5000,1560);
    CHECK(t.done && t.triggered && t.post==0U);
    begin(); push(1560,1560); FocTrace_Freeze(&t);
    FocTrace_Push(&t,&m,&c,1560,1560); CHECK(m.pairs==1U && t.physical==1U);
    /* External interlock Freeze does not call qualifier; no continued sampling. */
    puts("FAILURE TRACE PASS: chronology, exact unchanged qualifier, extrema witnesses, 16 post cap");
    return 0;
}
