/* ARM-compiled RAM decoder schema; never linked into a firmware image. */
#include <stddef.h>
#include "foc_feedback_safety_candidate.h"
#define P(field) (offsetof(FocFeedbackSafety,protection)+offsetof(FocFilteredProtection,field))
const uint32_t cur_confirm_layout[] = {
    sizeof(FocFeedbackSafety), P(pending), P(good_samples), P(confirm_cycles),
    P(cur_confirm_enter_count), P(cur_confirm_clear_count), P(cur_confirm_fault_count),
    P(cur_confirm_max_cycles), P(cur_confirm_max_elapsed_us)
};
