#include <stdio.h>
#include <stdlib.h>
#include "foc_overcurrent_shadow.h"
#include "foc_current_trend4.h"
#define CHECK(x) do { if (!(x)) { fprintf(stderr,"line %d: %s\n",__LINE__,#x); exit(1); } } while (0)
int main(void)
{
    FocOcShadow s;
    FocOcShadow_Begin(&s);
    FocOcShadow_Push(&s,1,1,1);
    CHECK(FocOcShadow_Pending(&s)==1 && !s.phase[0].singles && !s.confirmed_mask);
    FocOcShadow_Push(&s,2,0,1);
    CHECK(FocOcShadow_Pending(&s)==1 && !s.phase[0].singles);
    FocOcShadow_Push(&s,3,0,1);
    CHECK(!FocOcShadow_Pending(&s) && s.phase[0].singles==1);
    FocOcShadow_Begin(&s);
    FocOcShadow_Push(&s,1,2,1); FocOcShadow_Push(&s,2,2,1);
    CHECK(s.confirmed_mask==2 && !s.phase[1].singles);
    FocOcShadow_Push(&s,3,0,1); CHECK(s.confirmed_mask==2);
    FocOcShadow_Begin(&s);
    FocOcShadow_Push(&s,1,4,1); FocOcShadow_Push(&s,2,0,1); FocOcShadow_Push(&s,3,4,1);
    CHECK(s.confirmed_mask==4 && !s.phase[2].singles);
    FocOcShadow_Begin(&s);
    FocOcShadow_Push(&s,1,1,1); FocOcShadow_Push(&s,2,2,1); FocOcShadow_Push(&s,3,4,1);
    CHECK(!s.confirmed_mask && s.phase[0].singles==1); /* Independent phases. */
    FocOcShadow_Begin(&s);
    for (unsigned n=1;n<=9;++n) FocOcShadow_Push(&s,n,n%3==1?1:0,1);
    CHECK(s.noise_mask==1 && s.phase[0].singles==3 && !s.confirmed_mask);
    FocOcShadow_Begin(&s);
    for (unsigned n=1;n<=81;++n) FocOcShadow_Push(&s,n,n%39==1?1:0,1);
    CHECK(!s.noise_mask && s.phase[0].singles==3); /* Old singles expire. */
    FocOcShadow_Begin(&s);
    FocOcShadow_Push(&s,1,1,1); FocOcShadow_Push(&s,3,1,1);
    CHECK(s.gaps==1 && !s.confirmed_mask && FocOcShadow_Pending(&s)==1);
    FocOcShadow_Push(&s,4,0,0); CHECK(s.invalid==1 && !s.phase[0].singles);
    FocOcShadow_Push(&s,5,8,1); CHECK(s.invalid==2);
    FocOcShadow_Begin(&s);
    FocOcShadow_Push(&s,UINT32_MAX,1,1); FocOcShadow_Push(&s,0,1,1);
    CHECK(!s.gaps && s.confirmed_mask==1);
    s.samples=s.phase[0].hits=UINT32_MAX;
    FocOcShadow_Push(&s,1,1,1); CHECK(s.samples==UINT32_MAX && s.phase[0].hits==UINT32_MAX);
    CHECK(FocOcShadow_Mask(4.0f,-4.0f,0.0f,4.0f)==0);
    CHECK(FocOcShadow_Mask(2.3f,2.3f,-4.6f,4.0f)==4);
    CHECK(FocOcShadow_Mask(-4.1f,4.1f,0.0f,4.0f)==3);
    /* No shadow confirmation required by the real, immediate raw predicate. */
    FocOcShadow_Begin(&s); FocOcShadow_Push(&s,1,1,1);
    CHECK(!s.confirmed_mask && FocTrend4_RawTrip(2400,1560,1560,1560,
          3300.0f/(4095.0f*120.0f),4.0f));
    CHECK(FocTrend4_Select(1560,1560,2400,1560)==1560);
    puts("shadow states, independent phases, gaps, invalid, wrap, saturation, hard-trip PASS");
    return 0;
}
