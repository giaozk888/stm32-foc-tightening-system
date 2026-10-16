#include "foc_current_median.h"
#if defined(FOC_ADAPTIVE_REFERENCE)
#include "foc_adaptive_reference.h"
#define FocCurrentMedian_Push RefAdaptive_Push
#endif
__attribute__((noinline)) FOC_HOT_PATH int AdaptiveFilterProbe(FocCurrentMedian *s,
    uint16_t u,uint16_t v,uint16_t *fu,uint16_t *fv)
{ return FocCurrentMedian_Push(s,u,v,fu,fv); }
