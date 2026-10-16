/* Saved ADC data ONLY. Execute the identical C feedback/protection kernel.
 * Synthetic 50 us timestamps/zero angle do not qualify real acquisition timing. */
#include <stdio.h>
#include <stdlib.h>
#include "foc_feedback_safety_candidate.h"
#ifndef FOC_REPLAY_WINDOW_MAX
#define FOC_REPLAY_WINDOW_MAX 3U
#endif
#ifndef FOC_REPLAY_STREAK_MAX
#define FOC_REPLAY_STREAK_MAX 2U
#endif
int main(int argc, char **argv)
{
    if (argc != 3) return 2;
    char *end_u, *end_v;
    unsigned long zu = strtoul(argv[1], &end_u, 10), zv = strtoul(argv[2], &end_v, 10);
    if (*end_u || *end_v || zu > 4095U || zv > 4095U) return 2;
    FocFeedbackSafety s;
    FocFeedbackSafetyConfig cfg = {
        .protection = {4.0f, 100U, 100U, FOC_REPLAY_WINDOW_MAX, FOC_REPLAY_STREAK_MAX},
        .zero_u = (uint16_t)zu, .zero_v = (uint16_t)zv,
        .count_to_A = 3300.0f / (4095.0f * 120.0f)
    };
    if (FocFeedbackSafety_Begin(&s, cfg, 0U) != FOC_OC_CLEAR) return 3;
    unsigned u, v;
    uint32_t n = 0U, consumed = 0U, pending = 0U, trip_seq = 0U;
    int read;
    while ((read = scanf("%u %u", &u, &v)) == 2) {
        if (u > 4095U || v > 4095U || n >= 1000000U) return 4;
        ++n;
        if (trip_seq) continue; /* Count file length, NEVER restart the protector. */
        FocOcConfirmResult result = FocFeedbackSafety_Push(&s, n, n*50U,
            (uint16_t)u, (uint16_t)v, 0.0f, 0U, 1U);
        if (result == FOC_OC_TRIPPED) trip_seq = n;
        if (result == FOC_OC_PENDING) ++pending;
        FocFeedbackFrame f;
        if (FocFeedbackSafety_Take(&s, n*50U, 0U, 1U, &f)) ++consumed;
    }
    if (read != EOF || n < 4U) return 5;
    printf("{\"input_pairs\":%lu,\"consumed\":%lu,\"repaired\":%lu,"
        "\"pending_pairs\":%lu,\"trip_seq\":%lu,\"reason\":%u,"
        "\"result\":%u,\"window_repairs\":%u,\"repair_streak\":%u,"
        "\"repair_window_max\":%u,\"repair_streak_max\":%u,\"motor_qualified\":false}\n",
        (unsigned long)n, (unsigned long)consumed,
        (unsigned long)s.protection.repaired_pairs, (unsigned long)pending,
        (unsigned long)trip_seq, (unsigned)s.protection.reason, (unsigned)s.protection.result,
        (unsigned)FocFp_Popcount(s.protection.repair_window), (unsigned)s.protection.repair_streak,
        (unsigned)cfg.protection.repair_hits_per_32,(unsigned)cfg.protection.repair_streak);
    return 0;
}
