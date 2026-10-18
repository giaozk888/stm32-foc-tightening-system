/* No new algorithm: audit state/counter invariants with the unchanged core. */
#include <stdio.h>
#include <stdlib.h>
#include "foc_current_fast_reject.h"
#define CHECK(x) do { if (!(x)) { fprintf(stderr,"FAIL %d: %s\n",__LINE__,#x); exit(1); } } while (0)
static FocCurrentValidation s;
static void begin(void) { FocCurrentValidation_Begin(&s,1562,1561); }
static int push(unsigned u,unsigned v) { return FocCurrentValidation_Push(&s,(uint16_t)u,(uint16_t)v); }
static void coherent(void)
{
    CHECK(s.state==FOC_CURRENT_TRACKING);
    CHECK(s.current_unresolved_consecutive==0U);
    CHECK(s.current_measurement_fault_count==0U);
}
int main(void)
{
    /* Every accepted pair clears unresolved and atomically rebases BOTH axes. */
    for (unsigned unresolved=0;unresolved<3U;++unresolved) {
        begin(); CHECK(push(1740,1561)==0);
        for (unsigned i=0;i<unresolved;++i) {
            unsigned u=i==0U?1300U:1900U;
            CHECK(push(u,1561)==0);
            CHECK(s.candidate.u==u && s.reference.u==1562U);
            CHECK(s.current_unresolved_consecutive==i+1U);
        }
        CHECK(push(1562,1561)==1); coherent();
        CHECK(push(1563,1562)==1); coherent();
        CHECK(s.reference.u==1563U && s.reference.v==1562U);
    }
    /* A settled in-range level cannot stay locked out: even if the first
     * return is unresolved, advancing candidate admits its next repetition. */
    for (unsigned u=1200U;u<=1900U;u+=7U) {
        begin(); CHECK(push(1740,1561)==0);
        int first=push(u,1561);
        CHECK(first>=0);
        CHECK(push(u,1561)==1); coherent();
        CHECK(s.reference.u==u && s.reference.v==1561U);
    }
    /* The measured final reference/raw is NOT a complete replay. Demonstrate
     * why predecessor candidate matters; do not label either synthetic case real. */
    FocCurrentValidation_Begin(&s,1514,1545);
    CHECK(push(1563,1561)==1); coherent(); /* TRACKING accepts distance 49. */
    FocCurrentValidation_Begin(&s,1514,1545);
    CHECK(push(1700,1545)==0);
    CHECK(push(1563,1561)==0); /* SUSPECT uses RETURN=25, not JUMP=60. */
    CHECK(s.current_unresolved_consecutive==1U && s.candidate.u==1563U);
    CHECK(push(1563,1561)==1); coherent();
    /* Three truly incoherent pairs must still trip; no exception or rebase. */
    begin(); CHECK(push(1740,1561)==0);
    CHECK(push(1300,1561)==0 && push(1900,1561)==0 && push(1200,1561)==-1);
    CHECK(s.current_unresolved_consecutive==3U && s.current_measurement_fault_count==1U);
    CHECK(push(1562,1561)==-1);
    /* Real captured EARLY recovery window; not the missing final-fault window.
     * Seed first accepted pair; subsequent reference is fully determined. */
    static const CurrentRawPair early[]={
        {1566,1563},{1560,1557},{1564,1562},{1558,1557},
        {1564,1563},{1560,1561},{1565,1563},{1563,1563},
        {1561,1563},{1897,1829},{1563,1561},{1562,1560},
        {1554,1554},{1568,1556},{1556,1556},{1562,1560}};
    begin();
    for (unsigned i=0;i<sizeof(early)/sizeof(early[0]);++i)
        CHECK(push(early[i].u,early[i].v)==(i==9U?0:1));
    coherent(); CHECK(s.current_confirmed_spike==1U && !s.current_unresolved_total);
    puts("PASS unchanged state invariants, candidate advancement, strict fault and early recovery replay");
    return 0;
}
