/* Offline-only ARM layout evidence; never linked into firmware. */
#include <stddef.h>
#include "foc_feedback_safety_candidate.h"
const uint32_t two_sample_layout[] = {
    sizeof(FocFeedbackSafety), offsetof(FocFeedbackSafety,validation),
    sizeof(FocCurrentValidation), offsetof(FocCurrentValidation,reference),
    offsetof(FocCurrentValidation,candidate), offsetof(FocCurrentValidation,state),
    offsetof(FocCurrentValidation,last_path), offsetof(FocFeedbackSafety,raw_trip_counts)
};
