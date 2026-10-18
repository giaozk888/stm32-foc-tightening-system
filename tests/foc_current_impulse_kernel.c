/* Externally visible boundary for offline ARM assembly audit only. */
#include "foc_current_fast_reject.h"
int FocCurrentImpulse_Kernel(FocCurrentValidation *s,uint16_t u,uint16_t v)
{ return FocCurrentValidation_Push(s,u,v); }
