/* Run the production IRQ wrapper around an intentionally integrating stub. */
#define main previous_adc_cases
#include "protected_adc_irq_host.c"
#undef main
int main(void)
{
    reset(); cl_session.state=CL_READY;
    foc_int_d_V=.75f; foc_int_q_V=-.75f;
    ProtectedLoop_AdcIrq();
    assert(math_calls==1U && ended==1U && !fault);
    assert(foc_int_d_V==0.0f && foc_int_q_V==0.0f);
    reset(); cl_session.state=CL_RUNNING;
    foc_int_d_V=.25f; foc_int_q_V=-.25f;
    ProtectedLoop_AdcIrq();
    assert(foc_int_d_V==.375f && foc_int_q_V==-.375f);
    reset(); cl_session.state=CL_FAULT;
    foc_int_d_V=.75f; foc_int_q_V=-.75f;
    ProtectedLoop_AdcIrq();
    assert(foc_int_d_V==0.0f && foc_int_q_V==0.0f);
    puts("PASS actual IRQ: shadow PI discarded, running PI retained");
    return 0;
}
