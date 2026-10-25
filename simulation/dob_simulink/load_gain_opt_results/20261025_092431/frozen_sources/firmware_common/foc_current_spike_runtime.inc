/* In the injected-pair callback. This experimental branch is build-gated
 * to output-locked profiles. Feed all physical pairs, not just accepted
 * edges; otherwise the return edge of one spike also loses a normal point.
 * Existing physical-step health counters and consecutive-fault guard remain.
 */
uint16_t spike_u, spike_v;
int spike_ready = FocCurrentMedian_Push(&current_spike_filter, u, v,
                                      &spike_u, &spike_v);
for (uint8_t i = 0U; i < 3U; ++i) {
#if defined(FOC_CURRENT_TREND4)
    /* Legacy fault snapshots hold chronological a,b,c, not four-ring indices. */
    uint8_t source=(uint8_t)((current_spike_filter.index+1U+i)%4U);
    current_med_u[i] = current_spike_filter.u[source];
    current_med_v[i] = current_spike_filter.v[source];
#else
    current_med_u[i] = current_spike_filter.u[i];
    current_med_v[i] = current_spike_filter.v[i];
#endif
}
#if defined(FOC_CURRENT_TREND4)
current_med_index = 0U;
current_med_count = current_spike_filter.count < 3U ? current_spike_filter.count : 3U;
#else
current_med_index = current_spike_filter.index;
current_med_count = current_spike_filter.count;
#endif
if (frame_ok != 0U) {
    current_reject_streak = 0U;
} else {
    int32_t abs_u = step_u >= 0 ? step_u : -step_u;
    int32_t abs_v = step_v >= 0 ? step_v : -step_v;
    current_reject_count++;
    current_reject_streak++;
    current_last_rejected_sum_counts = abs_u > abs_v ? abs_u : abs_v;
    if (current_reject_streak >= CURRENT_REJECT_STREAK_LIMIT) {
        adc_fault = 1U;
        HAL_GPIO_WritePin(DRIVER_SD_GPIO_Port, DRIVER_SD_Pin, GPIO_PIN_RESET);
    }
}
/* Replace only a marked CENTER with its endpoint mean. Both phases now
 * represent the same delayed center time. Normal centers
 * (including a persistent step) retain their original, delayed raw values.
 * Invalid ADC codes are not made plausible, and never published.
 */
if (spike_ready &&
    spike_u <= ADC_FULL_SCALE && spike_v <= ADC_FULL_SCALE && adc_fault == 0U) {
    int32_t spike_w = (int32_t)iw_zero_raw -
        ((int32_t)spike_u - iu_zero_raw) - ((int32_t)spike_v - iv_zero_raw);
    if (spike_w < 0) spike_w = 0;
    else if (spike_w > (int32_t)ADC_FULL_SCALE) spike_w = ADC_FULL_SCALE;
    iu_inj_raw = spike_u;
    iv_inj_raw = spike_v;
    iw_inj_raw = (uint16_t)spike_w;
    current_valid_count++;
}
