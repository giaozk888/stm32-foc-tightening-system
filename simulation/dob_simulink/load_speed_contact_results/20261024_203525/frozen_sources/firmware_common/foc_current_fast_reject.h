#ifndef FOC_CURRENT_FAST_REJECT_H
#define FOC_CURRENT_FAST_REJECT_H
#include <stdint.h>
#include "foc_hot_path.h"

/* Integer two-sample discriminator, NOT an overcurrent protection or proof of
 * physical noise. Keep the former 60-count jump gate. Return/confirm=25 is a
 * configurable INITIAL value from the larger P95 (25/20) of two unlabelled
 * output-off captures; not a running-current/di/dt calibration. */
#ifndef FOC_CURRENT_JUMP_THRESHOLD_COUNTS
#define FOC_CURRENT_JUMP_THRESHOLD_COUNTS 60U
#endif
#ifndef FOC_CURRENT_RETURN_TOL_COUNTS
#define FOC_CURRENT_RETURN_TOL_COUNTS 25U
#endif
#ifndef FOC_CURRENT_CONFIRM_TOL_COUNTS
#define FOC_CURRENT_CONFIRM_TOL_COUNTS 25U
#endif
#ifndef FOC_CURRENT_UNRESOLVED_LIMIT
#define FOC_CURRENT_UNRESOLVED_LIMIT 3U
#endif
#ifndef FOC_ENABLE_LEGACY_CURRENT_REPAIR
#define FOC_ENABLE_LEGACY_CURRENT_REPAIR 0
#endif
#if FOC_CURRENT_JUMP_THRESHOLD_COUNTS < 1 || FOC_CURRENT_JUMP_THRESHOLD_COUNTS > 4095
#error Invalid current jump threshold
#endif
#if FOC_CURRENT_RETURN_TOL_COUNTS < 1 || FOC_CURRENT_RETURN_TOL_COUNTS > FOC_CURRENT_JUMP_THRESHOLD_COUNTS || FOC_CURRENT_CONFIRM_TOL_COUNTS < 1 || FOC_CURRENT_CONFIRM_TOL_COUNTS > FOC_CURRENT_JUMP_THRESHOLD_COUNTS
#error Invalid current return/confirmation tolerance
#endif
#if FOC_CURRENT_UNRESOLVED_LIMIT < 1 || FOC_CURRENT_UNRESOLVED_LIMIT > 255
#error Invalid unresolved measurement limit
#endif
#if defined(FOC_FAST_CURRENT_REJECT) && FOC_ENABLE_LEGACY_CURRENT_REPAIR
#error Fast reject and historical current repair are mutually exclusive
#endif
#if defined(FOC_FAST_CURRENT_REJECT) && (defined(FOC_RC_DEFERRED_SHADOW) || defined(FOC_REPAIR_WINDOW_TRACE))
#error Historical repair observers cannot be combined with fast current rejection
#endif
#if defined(FOC_FAST_CURRENT_REJECT) && (!defined(FOC_PROTECTED_CLOSED_LOOP) || !defined(FOC_GUARD_FAST_PATH) || !defined(FOC_LATEST_ORIGINAL_FSM))
#error Fast reject requires the existing protected original-FSM and integer guardian binding
#endif

typedef struct { uint16_t u, v; } CurrentRawPair;
enum { FOC_CURRENT_TRACKING, FOC_CURRENT_SUSPECT };
enum { FOC_CURRENT_PATH_NONE, FOC_CURRENT_PATH_NORMAL,
       FOC_CURRENT_PATH_SUSPECT, FOC_CURRENT_PATH_UNRESOLVED };
typedef struct {
    uint32_t current_samples_total, current_suspect_total;
    uint32_t current_confirmed_spike, current_confirmed_transition;
    uint32_t current_unresolved_total, current_unresolved_consecutive;
    uint32_t current_unresolved_max_consecutive, current_measurement_fault_count;
    uint32_t current_recovered_after_unresolved;
    CurrentRawPair reference, candidate;
    uint8_t state, last_path;
} FocCurrentValidation;

FOC_HOT_INLINE void FocCurrentValidation_Inc(uint32_t *v)
{ if (*v != UINT32_MAX) ++*v; }
FOC_HOT_INLINE uint32_t FocCurrentValidation_Abs(int32_t v)
{ return (uint32_t)(v < 0 ? -v : v); }
FOC_HOT_INLINE uint32_t FocCurrentValidation_Distance(CurrentRawPair a, CurrentRawPair b)
{
    uint32_t u=FocCurrentValidation_Abs((int32_t)a.u-b.u);
    uint32_t v=FocCurrentValidation_Abs((int32_t)a.v-b.v);
    return u>v ? u : v;
}
/* Seed with the qualified zeros; never blindly accept the first physical pair.
 * Only the ADC owner writes state. Reinitialization is NOT a fault clear. */
static inline void FocCurrentValidation_Begin(FocCurrentValidation *s,
                                             uint16_t zero_u, uint16_t zero_v)
{
    *s = (FocCurrentValidation){0};
    s->reference = (CurrentRawPair){zero_u,zero_v};
}
/* Returns 1=use THIS pair, 0=freeze PI/PWM, -1=existing measurement fault.
 * reference itself is old_reference throughout SUSPECT; never channel-mix.
 * A coherent persistent transition rebases it, avoiding last-valid lockout.
 * Only Case C increments unresolved. Initial suspicion consumes one held
 * period BEFORE those 3 unresolved periods (4 held periods total at limit=3).
 * Independent raw safety still sees every pair before this selector.
 */
FOC_HOT_INLINE int FocCurrentValidation_Push(FocCurrentValidation *s,
                                           uint16_t u, uint16_t v)
{
    if (s->current_measurement_fault_count) return -1; /* latched until Begin */
    FocCurrentValidation_Inc(&s->current_samples_total);
    CurrentRawPair next={u,v};
    s->last_path=FOC_CURRENT_PATH_NORMAL;
    if (u>4095U || v>4095U) goto unresolved; /* caller raw safety trips first */
    uint32_t d_old=FocCurrentValidation_Distance(next,s->reference);
    if (s->state==FOC_CURRENT_TRACKING) {
        if (d_old<=FOC_CURRENT_JUMP_THRESHOLD_COUNTS) {
            s->reference=next;
            return 1;
        }
        s->candidate=next;
        s->state=FOC_CURRENT_SUSPECT;
        s->last_path=FOC_CURRENT_PATH_SUSPECT;
        FocCurrentValidation_Inc(&s->current_suspect_total);
        return 0;
    }
    if (d_old<=FOC_CURRENT_RETURN_TOL_COUNTS) {
        /* Only a single unaccepted candidate can be called isolated spike.
         * Returning after a longer unresolved run is recovery, not a spike. */
        if (!s->current_unresolved_consecutive)
            FocCurrentValidation_Inc(&s->current_confirmed_spike);
        else FocCurrentValidation_Inc(&s->current_recovered_after_unresolved);
    } else {
        uint32_t d_cand=FocCurrentValidation_Distance(next,s->candidate);
        /* Require candidate proximity AND strictly nearer than old reference.
         * <=CONFIRM is stable new level; CONFIRM..JUMP permits an outward ramp
         * only (distance from old must not shrink). No arbitrary large jumps.
         * Both samples are already within existing 12-bit raw bounds. */
        if (d_cand<d_old &&
            (d_cand<=FOC_CURRENT_CONFIRM_TOL_COUNTS ||
             (d_cand<=FOC_CURRENT_JUMP_THRESHOLD_COUNTS &&
              d_old>=FocCurrentValidation_Distance(s->candidate,s->reference))))
            FocCurrentValidation_Inc(&s->current_confirmed_transition);
        else goto unresolved;
    }
    s->reference=next;
    s->state=FOC_CURRENT_TRACKING;
    s->current_unresolved_consecutive=0U;
    return 1;
unresolved:
    s->last_path=FOC_CURRENT_PATH_UNRESOLVED;
    FocCurrentValidation_Inc(&s->current_unresolved_total);
    FocCurrentValidation_Inc(&s->current_unresolved_consecutive);
    if (s->current_unresolved_consecutive>s->current_unresolved_max_consecutive)
        s->current_unresolved_max_consecutive=s->current_unresolved_consecutive;
    if (u<=4095U && v<=4095U) s->candidate=next;
    s->state=FOC_CURRENT_SUSPECT;
    if (s->current_unresolved_consecutive>=FOC_CURRENT_UNRESOLVED_LIMIT) {
        FocCurrentValidation_Inc(&s->current_measurement_fault_count);
        return -1;
    }
    return 0;
}

/* Task-side formatting only; no division or output in the ISR. */
typedef struct {
    uint32_t last_cycles, max_cycles, normal_last_cycles, normal_max_cycles;
    uint32_t suspect_last_cycles, suspect_max_cycles;
    uint32_t unresolved_last_cycles, unresolved_max_cycles, deadline_miss_count;
} FocCurrentCycleStats;
#define FOC_CURRENT_DEADLINE_CYCLES 8500U /* 170 MHz / 20 kHz, verified at init */
static inline int FocCurrentCycles_Record(FocCurrentCycleStats *s,
                                         uint32_t elapsed, uint8_t path)
{
    s->last_cycles = elapsed;
    if (elapsed > s->max_cycles) s->max_cycles = elapsed;
    if (path == FOC_CURRENT_PATH_NORMAL) {
        s->normal_last_cycles = elapsed;
        if (elapsed > s->normal_max_cycles) s->normal_max_cycles = elapsed;
    } else if (path == FOC_CURRENT_PATH_SUSPECT) {
        s->suspect_last_cycles = elapsed;
        if (elapsed > s->suspect_max_cycles) s->suspect_max_cycles = elapsed;
    } else if (path == FOC_CURRENT_PATH_UNRESOLVED) {
        s->unresolved_last_cycles = elapsed;
        if (elapsed > s->unresolved_max_cycles) s->unresolved_max_cycles = elapsed;
    }
    if (elapsed >= FOC_CURRENT_DEADLINE_CYCLES) {
        FocCurrentValidation_Inc(&s->deadline_miss_count);
        return 1;
    }
    return 0;
}
#endif
