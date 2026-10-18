/* stdin/stdout exist only in this offline host adapter, never in the ISR. */
#include <stdio.h>
#include "foc_current_fast_reject.h"
int main(void)
{
    unsigned u,v;
    FocCurrentValidation s;
    if (scanf("%u %u",&u,&v)!=2 || u>4095U || v>4095U) return 2;
    FocCurrentValidation_Begin(&s,(uint16_t)u,(uint16_t)v);
    unsigned accepted=0,held=0;
    while (scanf("%u %u",&u,&v)==2) {
        if (u>4095U || v>4095U) return 3;
        int result=FocCurrentValidation_Push(&s,(uint16_t)u,(uint16_t)v);
        if (result>0) ++accepted; else ++held;
        if (result<0) break;
    }
    printf("{\"samples\":%u,\"accepted\":%u,\"held\":%u,\"suspect\":%u,"
        "\"spike\":%u,\"transition\":%u,\"unresolved\":%u,\"max_unresolved_run\":%u,"
        "\"fault\":%u,\"recovered\":%u,\"state\":%u,\"ref_u\":%u,\"ref_v\":%u}\n",
        (unsigned)s.current_samples_total,accepted,held,(unsigned)s.current_suspect_total,
        (unsigned)s.current_confirmed_spike,(unsigned)s.current_confirmed_transition,
        (unsigned)s.current_unresolved_total,(unsigned)s.current_unresolved_max_consecutive,
        (unsigned)s.current_measurement_fault_count,(unsigned)s.current_recovered_after_unresolved,
        (unsigned)s.state,(unsigned)s.reference.u,(unsigned)s.reference.v);
    return 0;
}
