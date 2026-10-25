/* First-trip publication, after SD shutdown and before valid-last DMB.
 * Raw/filtered currents are separate; the old IU/IV/IW fields retain the
 * original triggering-path semantics. Never infer harmlessness from pending. */
foc_current_trip_snapshot.shadow=foc_oc_shadow;
foc_current_trip_snapshot.raw_mask=FocOcShadow_Mask(physical_u_A,physical_v_A,physical_w_A,FOC_CURRENT_TRIP_A);
foc_current_trip_snapshot.filtered_mask=FocOcShadow_Mask(filtered_u_A,filtered_v_A,filtered_w_A,FOC_CURRENT_TRIP_A);
foc_current_trip_snapshot.trip_source=(physical_trip?1U:0U) |
    (foc_current_trip_snapshot.filtered_mask?2U:0U);
foc_current_trip_snapshot.raw_mA[0]=(int32_t)(physical_u_A*1000.0f);
foc_current_trip_snapshot.raw_mA[1]=(int32_t)(physical_v_A*1000.0f);
foc_current_trip_snapshot.raw_mA[2]=(int32_t)(physical_w_A*1000.0f);
foc_current_trip_snapshot.filtered_mA[0]=(int32_t)(filtered_u_A*1000.0f);
foc_current_trip_snapshot.filtered_mA[1]=(int32_t)(filtered_v_A*1000.0f);
foc_current_trip_snapshot.filtered_mA[2]=(int32_t)(filtered_w_A*1000.0f);
for (uint8_t i=0U;i<4U;++i) {
    uint8_t source=(uint8_t)((current_spike_filter.index+i)%4U);
    foc_current_trip_snapshot.trend_u[i]=current_spike_filter.u[source];
    foc_current_trip_snapshot.trend_v[i]=current_spike_filter.v[source];
}
foc_current_trip_snapshot.spike_mask=current_spike_filter.last_spike_mask;
foc_current_trip_snapshot.trend_pairs=foc_trend_pairs;
foc_current_trip_snapshot.trend_changed=foc_trend_changed;
foc_current_trip_snapshot.trend_u_changed=foc_trend_u_changed;
foc_current_trip_snapshot.trend_v_changed=foc_trend_v_changed;
