/* Included by normal APP main.c only when ESP_NETWORK_OBSERVER is enabled.
   One-way observations; ESP ingress allowlist and motor control are unchanged. */
static void NetworkObserver_Publish(uint8_t kind)
{
    net_sample_t s = {0};
    float pos, speed, iq, contact, post;
    uint16_t bus_raw, vdda;
    uint32_t bus_tick;
    uint8_t bus_valid, reference_valid, enc_valid, iq_valid;
    taskENTER_CRITICAL();
    s.seq = ++g_network_seq;
    s.uptime_ms = HAL_GetTick();
    s.run = g_network_run;
    s.cycle = (uint8_t)tightening_cycle_number;
    s.stage = (uint8_t)tightening_test_stage;
    s.outcome = (uint8_t)tightening_last_outcome;
    s.fault = (uint16_t)foc_fault_reason;
    s.kind = kind;
    enc_valid = encoder_valid;
    iq_valid = (foc_enable != 0U && adc_fault == 0U && foc_fault == 0U);
    if (enc_valid) s.flags |= NET_FLAG_ENCODER;
    if (iq_valid) s.flags |= NET_FLAG_IQ;
    if (Tightening_IsBusy()) s.flags |= NET_FLAG_BUSY;
    if (analog_safe_latched) s.flags |= NET_FLAG_SAFE;
    if (tightening_contact_confirmed) s.flags |= NET_FLAG_CONTACT;
    if (HAL_GPIO_ReadPin(DRIVER_SD_GPIO_Port, DRIVER_SD_Pin) == GPIO_PIN_SET)
        s.flags |= NET_FLAG_SD;
    if (foc_fault || adc_fault) s.flags |= NET_FLAG_FAULT;
    pos = encoder_position_deg; speed = encoder_speed_rpm; iq = foc_iq_A;
    contact = tightening_contact_position_deg; post = tightening_post_contact_travel_deg;
    bus_raw = analog_live_pc4_raw; vdda = analog_vdda_boot_mv;
    bus_tick = analog_live_last_tick_ms;
    bus_valid = analog_live_valid && analog_live_sample_count != 0U;
    reference_valid = analog_vdda_boot_valid;
    taskEXIT_CRITICAL();
    /* Never turn the existing diagnostic bus estimate into accepted sensing. */
    s.vbus_quality = NET_VBUS_UNQUALIFIED;
    if (!bus_valid || !reference_valid) s.vbus_quality |= NET_VBUS_UNAVAILABLE;
    if ((uint32_t)(s.uptime_ms - bus_tick) > ANALOG_LIVE_FRESH_MS)
        s.vbus_quality |= NET_VBUS_STALE;
    if (s.vbus_quality == NET_VBUS_UNQUALIFIED)
        s.vbus_mv = (uint32_t)(((uint64_t)bus_raw * vdda * ANALOG_VBUS_DIVIDER +
                                 ADC_FULL_SCALE / 2U) / ADC_FULL_SCALE);
    if (!isfinite(pos) || !isfinite(speed) || !isfinite(iq) ||
        !isfinite(contact) || !isfinite(post) || fabsf(pos) > 20000000.0f ||
        fabsf(speed) > 20000000.0f || fabsf(iq) > 2000000.0f ||
        fabsf(contact) > 20000000.0f || fabsf(post) > 20000000.0f) {
        taskENTER_CRITICAL(); g_network_drop++; taskEXIT_CRITICAL();
        return;
    }
    s.position_cdeg = (int32_t)(pos * 100.0f);
    s.speed_drpm = (int32_t)(speed * 10.0f);
    s.iq_ma = (int32_t)(iq * 1000.0f);
    s.contact_cdeg = (int32_t)(contact * 100.0f);
    s.post_cdeg = (int32_t)(post * 100.0f);
    RouterPacket_t packet = {0};
    packet.src = 1U; packet.dst = 2U; packet.type = ROUTER_PKT_TEXT;
    packet.ttl = ROUTER_DEFAULT_TTL; packet.seq = (uint16_t)s.seq;
    packet.length = (uint16_t)net_sample_format(&s, packet.payload, sizeof(packet.payload));
    /* Direct bounded ESP adapter: no broadcast onto the control console. */
    if (!packet.length || !EspLink_RouterTx(&packet)) {
        taskENTER_CRITICAL(); g_network_drop++; taskEXIT_CRITICAL();
    }
}
