/* Read-only diagnostics. No fault clear, protection configuration, or actuator
 * commands. First-trip records are immutable after valid-last publication. */
    else if (strcmp(cmd,"OC RAW POLICY")==0)
    {
        char shadow_line[225];
#if defined(FOC_FEEDBACK_SAFETY_BINDING)
        (void)Protocol_SendFormatted(shadow_line,sizeof(shadow_line),
            "%lu OK OC RAW POLICY RAW=VALIDITY_ONLY FILTERED=CONFIRM_2_OF_3 LIMIT_MA=4000 "
            "GUARD=TIM7_HARD_OFF MOTOR_QUALIFIED=0\r\n",(unsigned long)request_id);
#elif defined(FOC_FILTERED_OBSERVE_ONLY)
        (void)Protocol_SendFormatted(shadow_line,sizeof(shadow_line),
            "%lu OK OC RAW POLICY RAW=OBSERVE_POWER_OFF FILTERED=OBSERVE_POWER_OFF LIMIT_MA=4000 "
            "INVALID=STOP LOCK_LOSS=STOP MOTOR_QUALIFIED=0\r\n",(unsigned long)request_id);
#elif defined(FOC_RAW_OBSERVE_ONLY)
        (void)Protocol_SendFormatted(shadow_line,sizeof(shadow_line),
            "%lu OK OC RAW POLICY RAW=OBSERVE_POWER_OFF FILTERED=STOP LIMIT_MA=4000 "
            "INVALID=STOP LOCK_LOSS=STOP MOTOR_QUALIFIED=0\r\n",(unsigned long)request_id);
#else
        (void)Protocol_SendFormatted(shadow_line,sizeof(shadow_line),
            "%lu OK OC RAW POLICY RAW=STOP FILTERED=STOP LIMIT_MA=4000\r\n",
            (unsigned long)request_id);
#endif
    }
#if defined(FOC_FILTERED_OBSERVE_ONLY)
    else if (strcmp(cmd,"OC FILTERED STATUS")==0)
    {
        char shadow_line[225];
        uint32_t mask=__get_PRIMASK(); __disable_irq();
        FocOcShadow s=foc_filtered_oc_shadow;
        __set_PRIMASK(mask);
        (void)Protocol_SendFormatted(shadow_line,sizeof(shadow_line),
            "%lu OK OC FILTERED MODE=OBSERVE_POWER_OFF LIMIT_MA=4000 DELAY_PAIRS=1 "
            "N=%lu SEQ=%lu HIT=%lu,%lu,%lu LAST_MASK=%u MOTOR_QUALIFIED=0\r\n",
            (unsigned long)request_id,(unsigned long)s.samples,(unsigned long)s.last_seq,
            (unsigned long)s.phase[0].hits,(unsigned long)s.phase[1].hits,
            (unsigned long)s.phase[2].hits,s.last_mask);
    }
#endif
    else if (strcmp(cmd,"FAULT SHADOW")==0)
    {
        char shadow_line[225];
        if (!foc_current_trip_snapshot.valid) {
            (void)Protocol_SendFormatted(shadow_line,sizeof(shadow_line),
                "%lu OK FAULT SHADOW VALID=0 MODE=OBSERVE\r\n",(unsigned long)request_id);
        } else {
            __DMB();
            (void)Protocol_SendFormatted(shadow_line,sizeof(shadow_line),
                "%lu OK FAULT SHADOW VALID=1 MODE=OBSERVE SRC=%u RM=%u FM=%u "
                "RAW=%ld,%ld,%ld FILT=%ld,%ld,%ld PEND=%u CONF=%u NOISE=%u GAP=%lu INV=%lu\r\n",
                (unsigned long)request_id,foc_current_trip_snapshot.trip_source,
                foc_current_trip_snapshot.raw_mask,foc_current_trip_snapshot.filtered_mask,
                (long)foc_current_trip_snapshot.raw_mA[0],(long)foc_current_trip_snapshot.raw_mA[1],
                (long)foc_current_trip_snapshot.raw_mA[2],(long)foc_current_trip_snapshot.filtered_mA[0],
                (long)foc_current_trip_snapshot.filtered_mA[1],(long)foc_current_trip_snapshot.filtered_mA[2],
                foc_current_trip_snapshot.shadow.phase[0].pending |
                    (foc_current_trip_snapshot.shadow.phase[1].pending<<1U) |
                    (foc_current_trip_snapshot.shadow.phase[2].pending<<2U),
                foc_current_trip_snapshot.shadow.confirmed_mask,foc_current_trip_snapshot.shadow.noise_mask,
                (unsigned long)foc_current_trip_snapshot.shadow.gaps,(unsigned long)foc_current_trip_snapshot.shadow.invalid);
        }
    }
    else if (strcmp(cmd,"FAULT TREND")==0)
    {
        char shadow_line[225];
        if (!foc_current_trip_snapshot.valid) {
            (void)Protocol_SendFormatted(shadow_line,sizeof(shadow_line),
                "%lu OK FAULT TREND VALID=0\r\n",(unsigned long)request_id);
        } else {
            __DMB();
            (void)Protocol_SendFormatted(shadow_line,sizeof(shadow_line),
                "%lu OK FAULT TREND VALID=1 DELAY=1 U=%u,%u,%u,%u V=%u,%u,%u,%u "
                "REPLACED=%u N=%lu CHANGED=%lu CU=%lu CV=%lu\r\n",
                (unsigned long)request_id,foc_current_trip_snapshot.trend_u[0],foc_current_trip_snapshot.trend_u[1],
                foc_current_trip_snapshot.trend_u[2],foc_current_trip_snapshot.trend_u[3],
                foc_current_trip_snapshot.trend_v[0],foc_current_trip_snapshot.trend_v[1],
                foc_current_trip_snapshot.trend_v[2],foc_current_trip_snapshot.trend_v[3],
                foc_current_trip_snapshot.spike_mask,(unsigned long)foc_current_trip_snapshot.trend_pairs,
                (unsigned long)foc_current_trip_snapshot.trend_changed,(unsigned long)foc_current_trip_snapshot.trend_u_changed,
                (unsigned long)foc_current_trip_snapshot.trend_v_changed);
        }
    }
    else if (strcmp(cmd,"OC SHADOW STATUS")==0)
    {
        char shadow_line[225];
        uint32_t mask=__get_PRIMASK(); __disable_irq();
        FocOcShadow s=foc_oc_shadow;
        __set_PRIMASK(mask);
        (void)Protocol_SendFormatted(shadow_line,sizeof(shadow_line),
            "%lu OK OC SHADOW MODE=OBSERVE LIMIT_MA=4000 "
            "N=%lu SEQ=%lu PEND=%u CONF=%u NOISE=%u GAP=%lu INV=%lu "
            "HIT=%lu,%lu,%lu SINGLE=%lu,%lu,%lu\r\n",
            (unsigned long)request_id,(unsigned long)s.samples,(unsigned long)s.last_seq,
            FocOcShadow_Pending(&s),s.confirmed_mask,s.noise_mask,(unsigned long)s.gaps,(unsigned long)s.invalid,
            (unsigned long)s.phase[0].hits,(unsigned long)s.phase[1].hits,(unsigned long)s.phase[2].hits,
            (unsigned long)s.phase[0].singles,(unsigned long)s.phase[1].singles,(unsigned long)s.phase[2].singles);
    }
    else if (strcmp(cmd,"OC FILTER STATUS")==0)
    {
        char shadow_line[225];
        uint32_t mask=__get_PRIMASK(); __disable_irq();
        uint32_t n=foc_trend_pairs, changed=foc_trend_changed;
        uint32_t cu=foc_trend_u_changed, cv=foc_trend_v_changed;
        __set_PRIMASK(mask);
        (void)Protocol_SendFormatted(shadow_line,sizeof(shadow_line),
            "%lu OK OC FILTER MODE=OBSERVE WINDOW=32 EVENTS=3 PAIRS=%lu CHANGED=%lu CU=%lu CV=%lu\r\n",
            (unsigned long)request_id,(unsigned long)n,(unsigned long)changed,(unsigned long)cu,(unsigned long)cv);
    }
