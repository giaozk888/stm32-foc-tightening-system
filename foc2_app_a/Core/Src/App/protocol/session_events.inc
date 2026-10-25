/* App A protocol/session_events.inc: private binding, included once by main.c.
 * Keep the declared include order and original control/IRQ ownership. */
static uint8_t Tightening_IsBusy(void)
{
#if defined(FOC_INTENT_FSM_CANDIDATE)
    return TighteningFsm_Busy(&intent_fsm);
#else
    switch (tightening_test_stage)
    {
        case TIGHTEN_STATE_RUNDOWN:
        case TIGHTEN_STATE_CONTACT_STOP:
        case TIGHTEN_STATE_SEATING_IQ:
        case TIGHTEN_STATE_TIGHTEN_010:
        case TIGHTEN_STATE_TIGHTEN_012:
        case TIGHTEN_STATE_TIGHTEN_015:
        case TIGHTEN_STATE_HOLD:
            return 1U;

        default:
            return 0U;
    }
#endif
}


static const char *TighteningOutcome_Name(TighteningOutcome_t outcome)
{
    switch (outcome)
    {
        case TIGHTEN_OUTCOME_OK:
            return "OK";
        case TIGHTEN_OUTCOME_STOPPED:
            return "STOPPED";
        case TIGHTEN_OUTCOME_RUNDOWN_TIMEOUT:
            return "RUNDOWN_TIMEOUT";
        case TIGHTEN_OUTCOME_STOP_TIMEOUT:
            return "STOP_TIMEOUT";
        case TIGHTEN_OUTCOME_ABORT:
            return "ABORT";
        case TIGHTEN_OUTCOME_FAULT:
            return "FAULT";
        case TIGHTEN_OUTCOME_NO_ROTATION:
            return "NO_ROTATION";
        case TIGHTEN_OUTCOME_NONE:
        default:
            return "NONE";
    }
}


static void Protocol_SendTaggedLine(
    uint32_t request_id,
    const char *payload)
{
    char msg[256];

    (void)Protocol_SendFormatted(
        msg,
        sizeof(msg),
        "%lu %s\r\n",
        (unsigned long)request_id,
        (payload != NULL) ? payload : "");
}


static void Protocol_SendError(
    uint32_t request_id,
    ProtocolError_t code,
    const char *name)
{
    char msg[128];

    (void)Protocol_SendFormatted(
        msg,
        sizeof(msg),
        "%lu ERR %u %s\r\n",
        (unsigned long)request_id,
        (unsigned int)code,
        (name != NULL) ? name : "UNKNOWN");
}


static void Protocol_EspPingService(void)
{
    if ((protocol_esp_ping_pending != 0U) &&
        ((int32_t)(xTaskGetTickCount() -
                   protocol_esp_ping_deadline) >= 0))
    {
        const uint16_t request_id = protocol_esp_ping_request_id;
        protocol_esp_ping_pending = 0U;
        Protocol_SendError(request_id, PROTO_ERR_NOT_READY,
                           "ESP_PING_TIMEOUT");
    }
}


static void Protocol_EspPingHandlePacket(const RouterPacket_t *packet)
{
    uint16_t reply_id = 0U;

    if ((packet == NULL) ||
        (packet->ingress_port != ROUTER_PORT_ESP32) ||
        (packet->src != 2U) ||
        (packet->dst != ROUTER_LOCAL_NODE_ID) ||
        (packet->type != ROUTER_PKT_PROTOCOL) ||
        (EspPing_ParsePongPayload(packet->payload, &reply_id) == 0U) ||
        (protocol_esp_ping_pending == 0U) ||
        (reply_id != protocol_esp_ping_request_id) ||
        ((int32_t)(xTaskGetTickCount() -
                   protocol_esp_ping_deadline) >= 0))
    {
        return;
    }

    protocol_esp_ping_pending = 0U;
    Protocol_SendTaggedLine(reply_id, "OK ESP32 PONG");
}


static void TighteningSession_Begin(
    uint8_t routed,
    uint16_t owner_node,
    uint32_t request_id)
{
#if defined(ESP_NETWORK_OBSERVER)
    taskENTER_CRITICAL(); g_network_run++; taskEXIT_CRITICAL();
#endif
    g_tightening_session_routed = (routed != 0U) ? 1U : 0U;
    g_tightening_session_owner_node =
        (routed != 0U) ? owner_node : 0U;
    g_tightening_session_request_id = request_id;

    /* Publish active last, after the owner/correlation fields are valid. */
    __DMB();
    g_tightening_session_active = 1U;
}


static void TighteningSession_End(void)
{
    /*
     * Keep owner_node/request_id as the last-session diagnostic snapshot.
     * Stage 4.3 copies the terminal EVT into the reliable-event path before this function is called.
     */
    g_tightening_session_active = 0U;
    __DMB();
}


static uint8_t Protocol_AsyncEventEnqueue(
    uint8_t routed,
    uint16_t dst_node,
    const char *payload)
{
    ProtocolAsyncEvent_t evt;
    size_t len;

    if ((protocol_async_event_queue == NULL) || (payload == NULL))
    {
        g_protocol_async_event_queue_drop++;
        return 0U;
    }

    len = strlen(payload);
    if ((len == 0U) || (len > ROUTER_MAX_PAYLOAD))
    {
        g_protocol_async_event_queue_drop++;
        return 0U;
    }

    memset(&evt, 0, sizeof(evt));
    evt.routed = (routed != 0U) ? 1U : 0U;
    evt.dst_node = (evt.routed != 0U) ? dst_node : 0U;
    memcpy(evt.payload, payload, len + 1U);

    if (xQueueSend(protocol_async_event_queue, &evt, 0U) != pdPASS)
    {
        g_protocol_async_event_queue_drop++;
        return 0U;
    }

    g_protocol_async_event_enqueued++;
    return 1U;
}


static uint8_t Protocol_ReliableEventParseEid(
    const char *text,
    const char *prefix,
    uint32_t *eid_out)
{
    const char *p;
    char *endptr;
    unsigned long value;
    size_t prefix_len;

    if ((text == NULL) || (prefix == NULL) || (eid_out == NULL))
    {
        return 0U;
    }

    prefix_len = strlen(prefix);
    if (strncmp(text, prefix, prefix_len) != 0)
    {
        return 0U;
    }

    p = text + prefix_len;
    value = strtoul(p, &endptr, 10);

    if ((endptr == p) ||
        (value == 0UL) ||
        (value > 0xFFFFFFFFUL))
    {
        return 0U;
    }

    /* EVENT has more payload after EID; ACK ends immediately after EID. */
    if ((*endptr != '\0') && (*endptr != ' ') && (*endptr != '\t'))
    {
        return 0U;
    }

    *eid_out = (uint32_t)value;
    return 1U;
}


static uint8_t Protocol_ReliableEventTransmit(
    ProtocolReliableEvent_t *slot,
    uint8_t is_retry)
{
    uint16_t router_seq = 0U;
    uint8_t ok;

    if ((slot == NULL) || (slot->in_use == 0U))
    {
        return 0U;
    }

    if (is_retry != 0U)
    {
        g_protocol_reliable_event_retried++;
    }

    ok = Router_SendText(
        slot->dst_node,
        PROTOCOL_ROUTER_TYPE_EVENT,
        slot->payload,
        &router_seq);

    /* One initial send + bounded retry attempts. */
    slot->attempts++;
    slot->next_retry_tick =
        xTaskGetTickCount() +
        pdMS_TO_TICKS(PROTOCOL_RELIABLE_EVENT_RETRY_MS);

    if (ok != 0U)
    {
        g_protocol_async_event_route_ok++;
        g_protocol_reliable_event_sent++;
        return 1U;
    }

    g_protocol_async_event_route_fail++;
    g_protocol_reliable_event_no_route++;
    return 0U;
}


static uint8_t Protocol_ReliableEventStart(
    uint16_t dst_node,
    const char *payload)
{
    ProtocolReliableEvent_t *slot = NULL;
    uint32_t i;
    uint32_t eid;
    int n;

    if ((payload == NULL) ||
        (dst_node == 0U) ||
        (dst_node == ROUTER_BROADCAST_NODE) ||
        (dst_node == ROUTER_LOCAL_NODE_ID))
    {
        return 0U;
    }

    for (i = 0U; i < PROTOCOL_RELIABLE_EVENT_SLOTS; i++)
    {
        if (protocol_reliable_events[i].in_use == 0U)
        {
            slot = &protocol_reliable_events[i];
            break;
        }
    }

    if (slot == NULL)
    {
        g_protocol_reliable_event_table_full++;
        UART_SendLiteral("EVT RELIABLE TABLE FULL\r\n");
        return 0U;
    }

    eid = protocol_reliable_next_eid++;
    if (eid == 0U)
    {
        eid = protocol_reliable_next_eid++;
    }

    memset(slot, 0, sizeof(*slot));
    slot->eid = eid;
    slot->dst_node = dst_node;

    if (strncmp(payload, "EVT ", 4U) == 0)
    {
        n = snprintf(
            slot->payload,
            sizeof(slot->payload),
            "EVT EID=%lu %s",
            (unsigned long)eid,
            payload + 4U);
    }
    else
    {
        n = snprintf(
            slot->payload,
            sizeof(slot->payload),
            "EVT EID=%lu %s",
            (unsigned long)eid,
            payload);
    }

    if ((n <= 0) || ((size_t)n > ROUTER_MAX_PAYLOAD))
    {
        memset(slot, 0, sizeof(*slot));
        g_protocol_async_event_queue_drop++;
        UART_SendLiteral("EVT RELIABLE PAYLOAD TOO LONG\r\n");
        return 0U;
    }

    /* ProtocolTask is the only writer of the pending table. */
    slot->in_use = 1U;
    __DMB();
    g_protocol_reliable_event_created++;

    (void)Protocol_ReliableEventTransmit(slot, 0U);
    return 1U;
}


static uint8_t Protocol_ReliableEventAck(
    uint16_t src_node,
    uint32_t eid)
{
    uint32_t i;

    for (i = 0U; i < PROTOCOL_RELIABLE_EVENT_SLOTS; i++)
    {
        ProtocolReliableEvent_t *slot = &protocol_reliable_events[i];

        if ((slot->in_use != 0U) &&
            (slot->eid == eid) &&
            (slot->dst_node == src_node))
        {
            slot->in_use = 0U;
            __DMB();
            g_protocol_reliable_event_acked++;
            return 1U;
        }
    }

    g_protocol_reliable_event_bad_ack++;
    return 0U;
}


static uint32_t Protocol_ReliableEventPendingCount(void)
{
    uint32_t i;
    uint32_t count = 0U;

    for (i = 0U; i < PROTOCOL_RELIABLE_EVENT_SLOTS; i++)
    {
        if (protocol_reliable_events[i].in_use != 0U)
        {
            count++;
        }
    }

    return count;
}


static uint8_t Protocol_ReliableEventRxSeen(
    uint16_t src_node,
    uint32_t eid)
{
    TickType_t now = xTaskGetTickCount();
    uint32_t i;

    for (i = 0U; i < PROTOCOL_RELIABLE_RX_CACHE_SIZE; i++)
    {
        ProtocolReliableRxCache_t *entry =
            &protocol_reliable_rx_cache[i];

        if ((entry->valid != 0U) &&
            ((int32_t)(now - entry->expires_tick) >= 0))
        {
            entry->valid = 0U;
        }

        if ((entry->valid != 0U) &&
            (entry->src_node == src_node) &&
            (entry->eid == eid))
        {
            return 1U;
        }
    }

    i = protocol_reliable_rx_cache_cursor %
        PROTOCOL_RELIABLE_RX_CACHE_SIZE;
    protocol_reliable_rx_cache_cursor++;

    protocol_reliable_rx_cache[i].src_node = src_node;
    protocol_reliable_rx_cache[i].eid = eid;
    protocol_reliable_rx_cache[i].expires_tick =
        now + pdMS_TO_TICKS(PROTOCOL_RELIABLE_RX_CACHE_MS);
    protocol_reliable_rx_cache[i].valid = 1U;
    return 0U;
}


static void Protocol_ReliableEventHandleEventPacket(
    const RouterPacket_t *packet)
{
    uint32_t eid;
    uint8_t duplicate;
    char ack_payload[32];
    char dbg[ROUTER_MAX_PAYLOAD + 64U];
    uint16_t seq = 0U;

    if ((packet == NULL) ||
        (packet->src == 0U) ||
        (packet->src == ROUTER_BROADCAST_NODE) ||
        (Protocol_ReliableEventParseEid(
            packet->payload,
            "EVT EID=",
            &eid) == 0U))
    {
        g_protocol_reliable_event_bad_event++;
        UART_SendLiteral("EVT RX BAD EVENT FRAME\r\n");
        return;
    }

    duplicate = Protocol_ReliableEventRxSeen(packet->src, eid);
    if (duplicate != 0U)
    {
        g_protocol_reliable_event_rx_duplicate++;
    }
    else
    {
        g_protocol_reliable_event_rx++;

        /*
         * Stage 4.3 receiver-side delivery hook. For now delivery is a
         * reliable diagnostic line. A later controller/application layer can
         * replace this with a real event callback without changing the wire
         * protocol.
         */
        UART_SendFormatted(
            dbg,
            sizeof(dbg),
            "REMOTE EVENT SRC=%u %s\r\n",
            (unsigned int)packet->src,
            packet->payload);
    }

    /* ACK every valid copy, including a retry already seen before. */
    snprintf(
        ack_payload,
        sizeof(ack_payload),
        "EID=%lu",
        (unsigned long)eid);

    if (Router_SendText(
            packet->src,
            PROTOCOL_ROUTER_TYPE_EVENT_ACK,
            ack_payload,
            &seq) != 0U)
    {
        g_protocol_reliable_event_ack_tx++;
    }
    else
    {
        g_protocol_reliable_event_ack_tx_fail++;
    }
}


static void Protocol_ReliableEventHandleAckPacket(
    const RouterPacket_t *packet)
{
    uint32_t eid;

    if ((packet == NULL) ||
        (packet->src == 0U) ||
        (packet->src == ROUTER_BROADCAST_NODE) ||
        (Protocol_ReliableEventParseEid(
            packet->payload,
            "EID=",
            &eid) == 0U))
    {
        g_protocol_reliable_event_bad_ack++;
        return;
    }

    (void)Protocol_ReliableEventAck(packet->src, eid);
}


static void Protocol_ReliableEventService(uint32_t budget)
{
    TickType_t now = xTaskGetTickCount();
    uint32_t i;

    for (i = 0U;
         (i < PROTOCOL_RELIABLE_EVENT_SLOTS) && (budget > 0U);
         i++)
    {
        ProtocolReliableEvent_t *slot = &protocol_reliable_events[i];

        if (slot->in_use == 0U)
        {
            continue;
        }

        if ((int32_t)(now - slot->next_retry_tick) < 0)
        {
            continue;
        }

        if (slot->attempts >= PROTOCOL_RELIABLE_EVENT_MAX_ATTEMPTS)
        {
            char dbg[128];

            UART_SendFormatted(
                dbg,
                sizeof(dbg),
                "EVT RELIABLE GIVEUP EID=%lu DST=%u ATTEMPTS=%u\r\n",
                (unsigned long)slot->eid,
                (unsigned int)slot->dst_node,
                (unsigned int)slot->attempts);

            slot->in_use = 0U;
            __DMB();
            g_protocol_reliable_event_giveup++;
            budget--;
            continue;
        }

        (void)Protocol_ReliableEventTransmit(slot, 1U);
        budget--;
    }
}


static void Protocol_AsyncEventService(uint32_t budget)
{
    ProtocolAsyncEvent_t evt;

    while ((budget > 0U) &&
           (protocol_async_event_queue != NULL) &&
           (xQueueReceive(protocol_async_event_queue, &evt, 0U) == pdPASS))
    {
        if ((evt.routed != 0U) &&
            (evt.dst_node != 0U) &&
            (evt.dst_node != ROUTER_BROADCAST_NODE) &&
            (evt.dst_node != ROUTER_LOCAL_NODE_ID))
        {
            if (Protocol_ReliableEventStart(
                    evt.dst_node,
                    evt.payload) == 0U)
            {
                char dbg[96];

                UART_SendFormatted(
                    dbg,
                    sizeof(dbg),
                    "EVT RELIABLE START FAILED DST=%u\r\n",
                    (unsigned int)evt.dst_node);
            }
        }
        else
        {
            char line[ROUTER_MAX_PAYLOAD + 3U];

            if (UART_SendReliableFormatted(line, sizeof(line),
                                           "%s\r\n", evt.payload) != 0U)
            {
                g_protocol_async_event_local_ok++;
            }
        }

        budget--;
    }
}


static void Protocol_SendDeferredStartError(
    uint8_t routed,
    uint16_t dst_node,
    uint32_t request_id,
    const char *name)
{
    char payload[128];

    snprintf(
        payload,
        sizeof(payload),
        "EVT REQ=%lu ERROR RESULT=%s",
        (unsigned long)request_id,
        (name != NULL) ? name : "UNKNOWN");

    if (Protocol_AsyncEventEnqueue(
            routed,
            dst_node,
            payload) == 0U)
    {
        UART_SendLiteral("EVT ASYNC QUEUE FULL: START ERROR LOST\r\n");
    }
}


static void Protocol_SendCycleEvent(
    const char *event_name,
    const char *result_name)
{
    char payload[160];
    uint8_t routed = g_tightening_session_routed;
    uint16_t owner_node = g_tightening_session_owner_node;
    uint32_t request_id = g_tightening_session_request_id;

    if (result_name != NULL)
    {
        snprintf(
            payload,
            sizeof(payload),
            "EVT REQ=%lu %s RESULT=%s",
            (unsigned long)request_id,
            (event_name != NULL) ? event_name : "EVENT",
            result_name);
    }
    else
    {
        snprintf(
            payload,
            sizeof(payload),
            "EVT REQ=%lu %s",
            (unsigned long)request_id,
            (event_name != NULL) ? event_name : "EVENT");
    }

    if (Protocol_AsyncEventEnqueue(
            routed,
            owner_node,
            payload) == 0U)
    {
        UART_SendLiteral("EVT ASYNC QUEUE FULL: TERMINAL EVENT LOST\r\n");
    }

    /*
     * The queue item owns a copy of routed/destination/payload, so the
     * business session can be closed immediately after the terminal event is
     * accepted. The next START cannot accidentally overwrite this event.
     */
    TighteningSession_End();
}


#if defined(FOC_PWM_COMMON_MODE_ENABLE)
__attribute__((optimize("Oz"))) /* UART task report, not a controller. */
#endif
static void Protocol_PrintStatus(uint32_t request_id)
{
    char msg[384];
    int32_t pos_x100 =
        (int32_t)(encoder_position_deg * 100.0f);
    int32_t ctrl_x10 =
        (int32_t)(encoder_speed_rpm * 10.0f);
    int32_t det_x10 =
        (int32_t)(encoder_speed_detect_rpm * 10.0f);
    int32_t iqref_mA =
        (int32_t)(foc_iq_ref_A * 1000.0f);

    (void)Protocol_SendFormatted(
        msg,
        sizeof(msg),
        "%lu OK STATUS STAGE=%u BUSY=%u MODE=%s OUTCOME=%s CONTACT=%u "
        "START_REQ=%lu FLT=%u REASON=%lu "
        "POS=%ld.%02lddeg CTRL=%ld.%01ldrpm DET=%ld.%01ldrpm "
        "IqRef=%ldmA "
        "UTXQ=%lu UDROP=%lu UERR=%lu "
        "RXQ=%lu RXDROP=%lu RXBYTES=%lu\r\n",
        (unsigned long)request_id,
        (unsigned int)tightening_test_stage,
        (unsigned int)Tightening_IsBusy(),
        MotorControl_ModeName(motor_control_mode),
        TighteningOutcome_Name(tightening_last_outcome),
        (unsigned int)tightening_contact_confirmed,
        (unsigned long)tightening_cycle_request_id,
        (unsigned int)foc_fault,
        (unsigned long)foc_fault_reason,
        (long)(pos_x100 / 100),
        (long)labs(pos_x100 % 100),
        (long)(ctrl_x10 / 10),
        (long)labs(ctrl_x10 % 10),
        (long)(det_x10 / 10),
        (long)labs(det_x10 % 10),
        (long)iqref_mA,
        (unsigned long)UART_Async_GetQueuedBytes(),
        (unsigned long)UART_Async_GetDroppedBytes(),
        (unsigned long)UART_Async_GetDmaErrorCount(),
        (unsigned long)UART_RxDma_GetQueuedBytes(),
        (unsigned long)UART_RxDma_GetDroppedBytes(),
        (unsigned long)UART_RxDma_GetTotalBytes());
#if defined(FOC_INTENT_FSM_CANDIDATE)
    TighteningIntent_PrintStatus(request_id);
#endif
}


