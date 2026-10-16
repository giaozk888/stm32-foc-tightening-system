#include <assert.h>
#include <math.h>
#include "foc_raw_observe_policy.h"
#include "foc_current_trend4.h"
#include "foc_overcurrent_shadow.h"

int main(void)
{
    const float gain=0.00671f;
    /* Actual captured physical pairs: both raw W values cross 4 A, while
     * delayed feedback is healthy. Only the hard-off fixture can continue. */
    assert(FocTrend4_RawTrip(1906,1916,1564,1562,gain,4.0f));
    assert(FocTrend4_RawTrip(1099,1059,1564,1562,gain,4.0f));
    assert(!FocRawObserve_StopRequired(1906,1916,gain,-.006f,-.006f,.013f,4.0f,1));
    assert(!FocRawObserve_StopRequired(1099,1059,gain,-.006f,-.006f,.013f,4.0f,1));
    assert(FocRawObserve_StopRequired(1906,1916,gain,0,0,0,4,0));
    assert(FocRawObserve_StopRequired(4096,1562,gain,0,0,0,4,1));
    assert(FocRawObserve_StopRequired(1564,4096,gain,0,0,0,4,1));
    assert(FocRawObserve_StopRequired(1564,1562,NAN,0,0,0,4,1));
    assert(FocRawObserve_StopRequired(1564,1562,0,0,0,0,4,1));
    assert(FocRawObserve_StopRequired(1564,1562,gain,0,0,0,INFINITY,1));
    assert(FocRawObserve_StopRequired(1564,1562,gain,NAN,0,0,4,1));
    assert(FocRawObserve_StopRequired(1564,1562,gain,0,INFINITY,0,4,1));
#if defined(FOC_FILTERED_OBSERVE_ONLY)
    assert(!FocRawObserve_StopRequired(1564,1562,gain,0,0,4.01f,4,1));
    assert(!FocRawObserve_StopRequired(1564,1562,gain,-4.01f,0,0,4,1));
    assert(!FocRawObserve_StopRequired(1099,1059,gain,3.122f,3.377f,-6.5f,4,1));
    assert(FocRawObserve_StopRequired(1099,1059,gain,3.122f,3.377f,-6.5f,4,0));
#else
    assert(FocRawObserve_StopRequired(1564,1562,gain,0,0,4.01f,4,1));
    assert(FocRawObserve_StopRequired(1564,1562,gain,-4.01f,0,0,4,1));
#endif
    assert(!FocRawObserve_StopRequired(1564,1562,gain,4,0,0,4,1));

    /* Observe-only does not erase the raw event. Follow-up healthy pairs
     * allow diagnostic classification, not permission for motor control. */
    FocOcShadow s; FocOcShadow_Begin(&s);
    FocOcShadow_Push(&s,1,4,1);
    assert(s.phase[2].hits==1 && FocOcShadow_Pending(&s)==4);
    FocOcShadow_Push(&s,2,0,1); FocOcShadow_Push(&s,3,0,1);
    assert(s.phase[2].hits==1 && s.phase[2].singles==1);
    FocOcShadow filtered; FocOcShadow_Begin(&filtered);
    FocOcShadow_Push(&filtered,1,FocOcShadow_Mask(3.122f,3.377f,-6.5f,4),1);
    assert(filtered.phase[2].hits==1 && filtered.last_mask==4);
    assert(s.phase[2].singles==1); /* Separate observers, no shared counters. */
    return 0;
}
