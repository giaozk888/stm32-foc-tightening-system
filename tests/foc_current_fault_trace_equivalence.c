#include <assert.h>
#include <stdio.h>
#include "foc_feedback_safety_candidate.h"
/* Both compiled variants hash every byte of the actual initialized control
 * state and return values; only the external diagnostic ring differs. */
int main(void)
{
    uint32_t hash=2166136261U, seed=1234567U;
    for (unsigned boot=0;boot<30U;++boot) {
#if FOC_CURRENT_FAULT_TRACE_ENABLE
        foc_current_fault_trace=(FocCurrentTrace){0};
        foc_current_trace_frame=0;
#endif
        FocFeedbackSafety s;
        FocFeedbackSafetyConfig cfg={.protection={4.0f,100U,100U,6U,4U},
            .zero_u=1564,.zero_v=1561,.count_to_A=3300.0f/(4095.0f*120.0f)};
        assert(FocFeedbackSafety_Begin(&s,cfg,0)==FOC_OC_CLEAR);
        for (unsigned i=1;i<400U;++i) {
            seed=seed*1664525U+1013904223U;
            uint16_t u=(uint16_t)(1564+(int)((seed>>16)%131U)-65);
            uint16_t v=(uint16_t)(1561+(int)((seed>>8)%131U)-65);
            if (i>350U) { u=1018; v=2166; }
            FOC_TRACE_CALL(FocCurrentTrace_Pending((uint8_t)(i&1U)));
            unsigned r=FocFeedbackSafety_Push(&s,i,i*50U,u,v,.25f,0,1);
            FocFeedbackFrame frame;
            int ready=FocFeedbackSafety_Take(&s,i*50U,0,1,&frame);
            if (ready) { FOC_TRACE_CALL(FocCurrentTrace_Pi()); FOC_TRACE_CALL(FocCurrentTrace_Pwm()); }
            FOC_TRACE_CALL(FocCurrentTrace_End());
            hash=(hash^r)*16777619U; hash=(hash^(unsigned)ready)*16777619U;
            const unsigned char *bytes=(const unsigned char *)&s;
            for (unsigned j=0;j<sizeof s;++j) hash=(hash^bytes[j])*16777619U;
        }
    }
    printf("CONTROL_HASH=%08lx\n",(unsigned long)hash);
    return 0;
}
