/* App A protocol/command_dispatch.inc: private binding, included once by main.c.
 * Keep the declared include order and original control/IRQ ownership. */
#if defined(FOC_PREEMPT_COMMIT_PROBE)
/* Cold task-only command dispatch: size codegen ONLY for this diagnostic,
 * no command/protocol behavior changes and no control-kernel option changes. */
__attribute__((optimize("Os")))
#endif
static void Protocol_HandleLine(char *line)
{
    char *p;
    char *endptr;
    char *cmd;
    unsigned long request_ul;
    uint32_t request_id;
    size_t len;
    size_t i;
    char msg[192];
    char *arg;
    char *value_text;
    char *value_end;
    unsigned long value_ul;

    if (line == NULL)
    {
        return;
    }

    /*
     * Protocol V2 frame:
     *
     *     <REQ_ID> <COMMAND>\r\n
     *
     * Examples:
     *
     *     17 PING
     *     18 STATUS
     *     19 START
     *
     * REQ_ID=0 is reserved for parser/framing errors where the original
     * request cannot be reliably correlated.
     */

    p = line;
    while ((*p == ' ') || (*p == '\t'))
    {
        p++;
    }

    if (p != line)
    {
        memmove(line, p, strlen(p) + 1U);
    }

    len = strlen(line);
    while ((len > 0U) &&
           ((line[len - 1U] == ' ') ||
            (line[len - 1U] == '\t')))
    {
        line[len - 1U] = '\0';
        len--;
    }

    if (line[0] == '\0')
    {
        return;
    }

    request_ul = strtoul(line, &endptr, 10);

    if ((endptr == line) ||
        (request_ul == 0UL) ||
        (request_ul > 0xFFFFFFFFUL))
    {
        Protocol_SendError(
            0U,
            PROTO_ERR_BAD_ARGUMENT,
            "BAD_REQUEST_ID");
        return;
    }

    if ((*endptr != ' ') && (*endptr != '\t'))
    {
        Protocol_SendError(
            (uint32_t)request_ul,
            PROTO_ERR_BAD_ARGUMENT,
            "MISSING_COMMAND_SEPARATOR");
        return;
    }

    request_id = (uint32_t)request_ul;

    cmd = endptr;
    while ((*cmd == ' ') || (*cmd == '\t'))
    {
        cmd++;
    }

    if (*cmd == '\0')
    {
        Protocol_SendError(
            request_id,
            PROTO_ERR_BAD_ARGUMENT,
            "MISSING_COMMAND");
        return;
    }

    /*
     * Commands are case-insensitive; the request ID is already parsed.
     */
    for (i = 0U; cmd[i] != '\0'; i++)
    {
        cmd[i] = (char)toupper((unsigned char)cmd[i]);
    }

#if defined(ZERO_RETEST_BOOT)
    if (ZeroRetest_HandleCommand(request_id, cmd)) return;
#endif
#if defined(UART_FIRMWARE_TRANSFER)
    if (PW_UartFirmwareTransfer_Busy() &&
        (((strncmp(cmd, "FW ", 3U) == 0) && (strcmp(cmd, "FW STATUS") != 0)) ||
         (strncmp(cmd, "RPC ", 4U) == 0) ||
         ((strncmp(cmd, "XFER ", 5U) == 0) && (strncmp(cmd, "XFER ENGINE ", 12U) != 0))))
    {
        Protocol_SendError(request_id, PROTO_ERR_BUSY, "OFFICIAL_TRANSFER_OWNS_IAP");
        return;
    }
#endif
    if ((fw_update.active != 0U) &&
        (strncmp(cmd, "FW ", 3U) != 0) &&
        (strncmp(cmd, "RPC ", 4U) != 0) &&
        (strncmp(cmd, "XFER ", 5U) != 0) &&
        (strcmp(cmd, "PING") != 0) &&
        (strcmp(cmd, "STATUS") != 0) &&
        (strcmp(cmd, "SELFTEST STATUS") != 0) &&
        (strcmp(cmd, "EVT STATUS") != 0))
    {
        Protocol_SendError(
            request_id,
            PROTO_ERR_BUSY,
            "FW_UPDATE_ACTIVE");
        return;
    }

    if (strcmp(cmd, "EVT STATUS") == 0)
    {
        (void)Protocol_SendFormatted(
            msg,
            sizeof(msg),
            "%lu OK EVT1 PENDING=%lu CREATED=%lu SENT=%lu RETRY=%lu "
            "ACK=%lu GIVEUP=%lu TFULL=%lu NOROUTE=%lu\r\n",
            (unsigned long)request_id,
            (unsigned long)Protocol_ReliableEventPendingCount(),
            (unsigned long)g_protocol_reliable_event_created,
            (unsigned long)g_protocol_reliable_event_sent,
            (unsigned long)g_protocol_reliable_event_retried,
            (unsigned long)g_protocol_reliable_event_acked,
            (unsigned long)g_protocol_reliable_event_giveup,
            (unsigned long)g_protocol_reliable_event_table_full,
            (unsigned long)g_protocol_reliable_event_no_route);

        (void)Protocol_SendFormatted(
            msg,
            sizeof(msg),
            "%lu OK EVT2 RX=%lu DUPRX=%lu ACKTX=%lu ACKTXFAIL=%lu "
            "BADEVT=%lu BADACK=%lu QDROP=%lu\r\n",
            (unsigned long)request_id,
            (unsigned long)g_protocol_reliable_event_rx,
            (unsigned long)g_protocol_reliable_event_rx_duplicate,
            (unsigned long)g_protocol_reliable_event_ack_tx,
            (unsigned long)g_protocol_reliable_event_ack_tx_fail,
            (unsigned long)g_protocol_reliable_event_bad_event,
            (unsigned long)g_protocol_reliable_event_bad_ack,
            (unsigned long)g_protocol_async_event_queue_drop);
    }
    else if (strcmp(cmd, "ESP PING") == 0)
    {
        char ping_payload[24];
        uint16_t router_seq = 0U;

        if ((protocol_esp_ping_uart_local == 0U) ||
            (request_id > 65535U))
        {
            Protocol_SendError(request_id, PROTO_ERR_BAD_ARGUMENT,
                               "ESP_PING_COM5_ID_1_65535_ONLY");
        }
        else if (protocol_esp_ping_pending != 0U)
        {
            Protocol_SendError(request_id, PROTO_ERR_BUSY,
                               "ESP_PING_PENDING");
        }
        else
        {
            snprintf(ping_payload, sizeof(ping_payload),
                     "%lu PING", (unsigned long)request_id);
            protocol_esp_ping_request_id = (uint16_t)request_id;
            protocol_esp_ping_deadline =
                xTaskGetTickCount() + pdMS_TO_TICKS(2000U);
            protocol_esp_ping_pending = 1U;
            if (Router_SendText(2U, ROUTER_PKT_PROTOCOL,
                                ping_payload, &router_seq) == 0U)
            {
                protocol_esp_ping_pending = 0U;
                Protocol_SendError(request_id, PROTO_ERR_NOT_READY,
                                   "ESP_NO_ROUTE");
            }
            else
            {
                (void)Protocol_SendFormatted(msg, sizeof(msg),
                         "%lu OK ESP PING SENT SEQ=%u\r\n",
                         (unsigned long)request_id,
                         (unsigned int)router_seq);
            }
        }
    }
    else if (strcmp(cmd, "ROUTER STATUS") == 0)
    {
        RouterStatus_t status;

        Router_GetStatus(&status);

        (void)Protocol_SendFormatted(
            msg,
            sizeof(msg),
            "%lu OK ROUTER NODE=%u RX=%lu LOCAL=%lu FWD=%lu TX=%lu "
            "DRX=%lu DTX=%lu NOROUTE=%lu TTL=%lu DUP=%lu LOOP=%lu "
            "PARSE=%lu RXQFULL=%lu LOCALQFULL=%lu NAGE=%lu RAGE=%lu "
            "RPLYOK=%lu RPLYFAIL=%lu\r\n",
            (unsigned long)request_id,
            (unsigned int)status.local_node_id,
            (unsigned long)status.rx_packets,
            (unsigned long)status.local_delivered,
            (unsigned long)status.forwarded,
            (unsigned long)status.tx_packets,
            (unsigned long)status.discovery_rx,
            (unsigned long)status.discovery_tx,
            (unsigned long)status.dropped_no_route,
            (unsigned long)status.dropped_ttl,
            (unsigned long)status.dropped_duplicate,
            (unsigned long)status.dropped_self_loop,
            (unsigned long)status.parse_errors,
            (unsigned long)status.rx_queue_full,
            (unsigned long)status.local_queue_full,
            (unsigned long)status.nodes_aged_out,
            (unsigned long)status.routes_aged_out,
            (unsigned long)protocol_reply_route_ok,
            (unsigned long)protocol_reply_route_fail);
    }
    else if (strcmp(cmd, "ROUTER NODES") == 0)
    {
        uint32_t count = Router_GetNodeCount();
        uint32_t idx;

        (void)Protocol_SendFormatted(
            msg,
            sizeof(msg),
            "%lu " "OK ROUTER NODES COUNT=%lu" "\r\n",
            (unsigned long)request_id,
            (unsigned long)count);

        for (idx = 0U; idx < count; idx++)
        {
            RouterNodeInfo_t node;

            if (Router_GetNode(idx, &node) != 0U)
            {
                (void)Protocol_SendFormatted(
            msg,
            sizeof(msg),
            "%lu " "NODE ID=%u PORT=%s AGE_MS=%lu RX=%lu FLAGS=0x%02X" "\r\n",
            (unsigned long)request_id,
            (unsigned int)node.node_id,
            Router_PortName(node.port),
            (unsigned long)node.age_ms,
            (unsigned long)node.rx_packets,
            (unsigned int)node.flags);
            }
        }

        Protocol_SendTaggedLine(request_id, "END ROUTER NODES");
    }
    else if (strcmp(cmd, "ROUTER ROUTES") == 0)
    {
        uint32_t count = Router_GetRouteCount();
        uint32_t idx;

        (void)Protocol_SendFormatted(
            msg,
            sizeof(msg),
            "%lu " "OK ROUTER ROUTES COUNT=%lu" "\r\n",
            (unsigned long)request_id,
            (unsigned long)count);

        for (idx = 0U; idx < count; idx++)
        {
            RouterRouteInfo_t route;

            if (Router_GetRoute(idx, &route) != 0U)
            {
                (void)Protocol_SendFormatted(
            msg,
            sizeof(msg),
            "%lu " "ROUTE DST=%u PORT=%s METRIC=%u AGE_MS=%lu FLAGS=0x%02X" "\r\n",
            (unsigned long)request_id,
            (unsigned int)route.destination,
            Router_PortName(route.port),
            (unsigned int)route.metric,
            (unsigned long)route.age_ms,
            (unsigned int)route.flags);
            }
        }

        Protocol_SendTaggedLine(request_id, "END ROUTER ROUTES");
    }
    else if (strcmp(cmd, "ROUTER DISCOVER") == 0)
    {
        uint16_t router_seq = 0U;

        if (Router_SendHello(&router_seq) == 0U)
        {
            Protocol_SendError(
                request_id,
                PROTO_ERR_NOT_READY,
                "ROUTER_NO_TRANSPORT");
        }
        else
        {
            (void)Protocol_SendFormatted(
                msg,
                sizeof(msg),
                "%lu OK ROUTER DISCOVER HELLO_SEQ=%u\r\n",
                (unsigned long)request_id,
                (unsigned int)router_seq);
        }
    }
    else if (strcmp(cmd, "ROUTER CONFIG") == 0)
    {
        (void)Protocol_SendFormatted(
            msg,
            sizeof(msg),
            "%lu OK ROUTER CONFIG HELLO_MS=%u NODE_TIMEOUT_MS=%u "
            "ROUTE_TIMEOUT_MS=%u DUP_WINDOW_MS=%u\r\n",
            (unsigned long)request_id,
            (unsigned int)ROUTER_DISCOVERY_INTERVAL_MS,
            (unsigned int)ROUTER_NODE_TIMEOUT_MS,
            (unsigned int)ROUTER_ROUTE_TIMEOUT_MS,
            (unsigned int)ROUTER_DUP_WINDOW_MS);
    }
    else if (strcmp(cmd, "ROUTER CLEAR") == 0)
    {
        Router_ClearDynamic();

        (void)Protocol_SendFormatted(
            msg,
            sizeof(msg),
            "%lu OK ROUTER CLEAR DYNAMIC=1\r\n",
            (unsigned long)request_id);
    }
    else if (strncmp(cmd, "ROUTER SEND ", 12U) == 0)
    {
        char *dst_text = cmd + 12U;
        char *dst_end;
        char *payload;
        unsigned long dst_ul;
        uint16_t router_seq = 0U;

        while ((*dst_text == ' ') || (*dst_text == '\t'))
        {
            dst_text++;
        }

        dst_ul = strtoul(dst_text, &dst_end, 10);

        if ((dst_end == dst_text) ||
            (dst_ul == 0UL) ||
            (dst_ul > 0xFFFFUL))
        {
            Protocol_SendError(
                request_id,
                PROTO_ERR_BAD_ARGUMENT,
                "ROUTER_BAD_DST");
        }
        else
        {
            payload = dst_end;
            while ((*payload == ' ') || (*payload == '\t'))
            {
                payload++;
            }

            if (*payload == '\0')
            {
                Protocol_SendError(
                    request_id,
                    PROTO_ERR_BAD_ARGUMENT,
                    "ROUTER_EMPTY_PAYLOAD");
            }
            else if (Router_SendText(
                         (uint16_t)dst_ul,
                         ROUTER_PKT_TEXT,
                         payload,
                         &router_seq) == 0U)
            {
                Protocol_SendError(
                    request_id,
                    PROTO_ERR_NOT_READY,
                    "ROUTER_NO_ROUTE");
            }
            else
            {
                (void)Protocol_SendFormatted(
                    msg,
                    sizeof(msg),
                    "%lu OK ROUTER SEND DST=%lu SEQ=%u\r\n",
                    (unsigned long)request_id,
                    dst_ul,
                    (unsigned int)router_seq);
            }
        }
    }
    else if ((strcmp(cmd, "MODBUS PROBE") == 0) ||
             (strncmp(cmd, "MODBUS PROBE ", 13U) == 0))
    {
        unsigned long baud = 9600UL;
        unsigned long slave = 255UL;
        unsigned long function = 1UL;
        unsigned long address = 0UL;
        char parity = 'N';
        char extra;
        int fields = 0;
        ModbusJob_t job = {0};

        if (strcmp(cmd, "MODBUS PROBE") != 0)
        {
            fields = sscanf(cmd, "MODBUS PROBE %lu %lu %lu %lu %c %c",
                            &baud, &slave, &function, &address,
                            &parity, &extra);
            if ((fields != 4) && (fields != 5))
            {
                Protocol_SendError(request_id, PROTO_ERR_BAD_ARGUMENT,
                    "MODBUS_USE_PROBE_BAUD_ID_FC_ADDR_[N|E]");
                return;
            }
        }
        if ((baud > 115200UL) || ((slave > 247UL) && (slave != 255UL)) ||
            (function > 4UL) || (address > 65535UL) ||
            ((parity != 'N') && (parity != 'E')))
        {
            Protocol_SendError(request_id, PROTO_ERR_BAD_ARGUMENT,
                "MODBUS_INVALID_ARGUMENT");
            return;
        }
        if ((motor_control_mode != MOTOR_MODE_IDLE) ||
            (Tightening_IsBusy() != 0U))
        {
            Protocol_SendError(request_id, PROTO_ERR_BUSY,
                "MOTOR_NOT_IDLE");
            return;
        }

        job.request_id = request_id;
        job.type = MODBUS_JOB_READ;
        job.baud = (uint32_t)baud;
        job.slave = (uint8_t)slave;
        job.function = (uint8_t)function;
        job.address = (uint16_t)address;
        job.even_parity = parity == 'E' ? 1U : 0U;
        if (Modbus_Enqueue(&job) == 0U)
        {
            Protocol_SendError(request_id, PROTO_ERR_BUSY,
                               "MODBUS_QUEUE_FULL");
        }
    }
    else if (strncmp(cmd, "MODBUS RELAY ", 13U) == 0)
    {
        unsigned long relay;
        char action[8];
        char extra;
        uint8_t on;
        ModbusJob_t job = {0};

        if (sscanf(cmd, "MODBUS RELAY %lu %7s %c",
                   &relay, action, &extra) != 2 ||
            (relay < 1UL) || (relay > 4UL) ||
            ((strcmp(action, "ON") != 0) &&
             (strcmp(action, "OFF") != 0)))
        {
            Protocol_SendError(request_id, PROTO_ERR_BAD_ARGUMENT,
                "MODBUS_USE_RELAY_1_TO_4_ON_OR_OFF");
            return;
        }
        if ((motor_control_mode != MOTOR_MODE_IDLE) ||
            (Tightening_IsBusy() != 0U))
        {
            Protocol_SendError(request_id, PROTO_ERR_BUSY,
                "MOTOR_NOT_IDLE");
            return;
        }
        on = strcmp(action, "ON") == 0 ? 1U : 0U;
        job.request_id = request_id;
        job.type = MODBUS_JOB_RELAY;
        job.relay = (uint8_t)relay;
        job.on = on;
        if (Modbus_Enqueue(&job) == 0U)
        {
            Protocol_SendError(request_id, PROTO_ERR_BUSY,
                               "MODBUS_QUEUE_FULL");
        }
    }
    else if (strcmp(cmd, "MODBUS STATS") == 0)
    {
        (void)Protocol_SendFormatted(msg, sizeof(msg),
                 "%lu OK MODBUS STATS SUB=%lu DONE=%lu FAIL=%lu FULL=%lu TIMEOUT=%lu CRC=%lu RQ=%lu CQ=%lu\r\n",
                 (unsigned long)request_id,
                 (unsigned long)modbus_submitted,
                 (unsigned long)modbus_completed,
                 (unsigned long)modbus_failed,
                 (unsigned long)modbus_queue_full,
                 (unsigned long)modbus_timeout,
                 (unsigned long)modbus_crc_error,
                 (unsigned long)uxQueueMessagesWaiting(modbus_request_queue),
                 (unsigned long)uxQueueMessagesWaiting(modbus_completion_queue));
    }
    else if (strcmp(cmd, "PING") == 0)
    {
        Protocol_SendTaggedLine(request_id, "OK PING PONG");
    }
    else if (strcmp(cmd, "HELP") == 0)
    {
        Protocol_SendTaggedLine(
            request_id,
            "OK HELP VERSION=2 PARAMS=1 KVS=1 RPC=1 ALLOC=1 LOG=1");
        Protocol_SendTaggedLine(request_id, "FORMAT <REQ_ID> <COMMAND>");
        Protocol_SendTaggedLine(request_id, "CMD PING");
        Protocol_SendTaggedLine(request_id, "CMD MODBUS PROBE [BAUD ID FC ADDR [N|E]]");
        Protocol_SendTaggedLine(request_id, "CMD MODBUS RELAY <1..4> <ON|OFF>");
        Protocol_SendTaggedLine(request_id, "CMD MODBUS STATS");
        Protocol_SendTaggedLine(request_id, "CMD STATUS");
        Protocol_SendTaggedLine(request_id, "CMD ENC DIAG");
        Protocol_SendTaggedLine(request_id, "CMD ENC SAMPLE (ANALOG SAFE ONLY)");
        Protocol_SendTaggedLine(request_id, "CMD SELFTEST STATUS");
        Protocol_SendTaggedLine(request_id, "CMD FAULT SNAPSHOT");
        Protocol_SendTaggedLine(request_id, "CMD FAULT FILTER");
#if defined(FOC_CURRENT_TREND4)
        Protocol_SendTaggedLine(request_id, "CMD FAULT SHADOW");
        Protocol_SendTaggedLine(request_id, "CMD FAULT TREND");
        Protocol_SendTaggedLine(request_id, "CMD OC SHADOW STATUS");
        Protocol_SendTaggedLine(request_id, "CMD OC FILTER STATUS");
#endif
        Protocol_SendTaggedLine(request_id, "CMD ANALOG SAFE");
        Protocol_SendTaggedLine(request_id, "CMD ANALOG SAFE STATUS");
        Protocol_SendTaggedLine(request_id, "CMD ANALOG BOOT");
        Protocol_SendTaggedLine(request_id, "CMD ANALOG LIVE");
        Protocol_SendTaggedLine(request_id, "CMD ANALOG VOLT");
        Protocol_SendTaggedLine(request_id, "CMD ANALOG PAIR");
        Protocol_SendTaggedLine(request_id, "CMD ANALOG TRIPLE");
        Protocol_SendTaggedLine(request_id, "CMD ANALOG PC5 TRIPLE");
        Protocol_SendTaggedLine(request_id, "CMD ROUTER STATUS");
        Protocol_SendTaggedLine(request_id, "CMD ROUTER NODES");
        Protocol_SendTaggedLine(request_id, "CMD ROUTER ROUTES");
        Protocol_SendTaggedLine(request_id, "CMD ROUTER DISCOVER");
        Protocol_SendTaggedLine(request_id, "CMD ROUTER CONFIG");
        Protocol_SendTaggedLine(request_id, "CMD ROUTER CLEAR");
        Protocol_SendTaggedLine(request_id, "CMD ROUTER SEND <DST> <TEXT>");
        Protocol_SendTaggedLine(request_id, "CMD ESP PING (COM5 ONLY)");
        Protocol_SendTaggedLine(request_id, "CMD EVT STATUS");
        Protocol_SendTaggedLine(request_id, "ROUTER TYPE4=EVENT TYPE5=EVENT_ACK");
        Protocol_SendTaggedLine(request_id, "CMD START");
        Protocol_SendTaggedLine(request_id, "CMD STOP");
        Protocol_SendTaggedLine(request_id, "CMD RESULT");
        Protocol_SendTaggedLine(request_id, "CMD GET PARAMS");
        Protocol_SendTaggedLine(request_id, "CMD GET <PARAM>");
        Protocol_SendTaggedLine(request_id, "CMD SET <PARAM> <VALUE>");
        Protocol_SendTaggedLine(request_id, "CMD SAVE PARAMS");
        Protocol_SendTaggedLine(request_id, "CMD LOAD PARAMS");
        Protocol_SendTaggedLine(request_id, "CMD DEFAULT PARAMS");
        Protocol_SendTaggedLine(request_id, "CMD KVS STATUS");
        Protocol_SendTaggedLine(request_id, "CMD ALLOC STATUS");
        Protocol_SendTaggedLine(request_id, "CMD ALLOC TEST");
        Protocol_SendTaggedLine(request_id, "CMD LOG STATUS");
        Protocol_SendTaggedLine(request_id, "CMD LOG DUMP");
        Protocol_SendTaggedLine(request_id, "CMD LOG CLEAR");
        Protocol_SendTaggedLine(request_id, "CMD LOG LEVEL <DEBUG|INFO|WARN|ERROR|CRITICAL|FATAL>");
        Protocol_SendTaggedLine(request_id, "CMD LOG TEST <COUNT>");
        Protocol_SendTaggedLine(request_id, "CMD LOG TOKEN TEST <COUNT>");
        Protocol_SendTaggedLine(request_id, "CMD LOG ROUTER STATUS");
        Protocol_SendTaggedLine(request_id, "CMD LOG SUBSCRIBERS");
        Protocol_SendTaggedLine(request_id, "CMD LOG SUBSCRIBE [NODE] <LEVEL> <SECONDS>");
        Protocol_SendTaggedLine(request_id, "CMD LOG UNSUBSCRIBE [NODE]");
        Protocol_SendTaggedLine(request_id, "CMD RPC INFO");
        Protocol_SendTaggedLine(request_id, "CMD RPC [CALL] <PW_RPC_PACKET_HEX>");
        Protocol_SendTaggedLine(request_id, "CMD XFER STATUS");
        Protocol_SendTaggedLine(request_id, "CMD XFER RESET");
        Protocol_SendTaggedLine(request_id, "CMD BOOT STATUS");
        Protocol_SendTaggedLine(request_id, "CMD BOOT A");
        Protocol_SendTaggedLine(request_id, "CMD BOOT B");
        Protocol_SendTaggedLine(request_id, "CMD FW STATUS");
        Protocol_SendTaggedLine(request_id, "CMD FW CONFIRM");
        Protocol_SendTaggedLine(request_id, "CMD FW BEGIN <SIZE_DEC> <CRC32_HEX>");
        Protocol_SendTaggedLine(request_id, "CMD FW DATA <OFFSET_HEX> <HEX_BYTES>");
        Protocol_SendTaggedLine(request_id, "CMD FW END");
        Protocol_SendTaggedLine(request_id, "CMD FW ABORT");
        Protocol_SendTaggedLine(request_id, "INFO TRIAL=AUTO_CONFIRM_5S FAIL_RESET_12S");
        Protocol_SendTaggedLine(request_id, "CMD HELP");
        Protocol_SendTaggedLine(request_id, "ERR 100 UNKNOWN_COMMAND");
        Protocol_SendTaggedLine(request_id, "ERR 101 BUSY");
        Protocol_SendTaggedLine(request_id, "ERR 102 LINE_TOO_LONG");
        Protocol_SendTaggedLine(request_id, "ERR 103 BAD_ARGUMENT");
        Protocol_SendTaggedLine(request_id, "ERR 104 NOT_READY");
        Protocol_SendTaggedLine(request_id, "ERR 105 FAULT");
        Protocol_SendTaggedLine(request_id, "ERR 106 ROTOR_MOVING");
        Protocol_SendTaggedLine(request_id, "ERR 107 FLASH_ERROR");
        Protocol_SendTaggedLine(request_id, "ERR 108 NO_VALID_PARAMS");
        Protocol_SendTaggedLine(request_id, "ERR 109 FW_STATE");
        Protocol_SendTaggedLine(request_id, "ERR 110 FW_CRC");
        Protocol_SendTaggedLine(request_id, "ERR 111 FW_RANGE");
        Protocol_SendTaggedLine(request_id, "ERR 112 FW_SEQUENCE");
        Protocol_SendTaggedLine(request_id, "END HELP");
    }
    else if (strcmp(cmd, "STATUS") == 0)
    {
        Protocol_PrintStatus(request_id);
    }
    else if (strcmp(cmd, "ENC DIAG") == 0)
    {
#if defined(AS5047P_SPI_DMA)
        AsDmaStats dma_stats;
        AS5047P_DmaGetStats(&dma_stats);
        (void)Protocol_SendFormatted(msg, sizeof(msg),
                 "%lu OK ENC DMA READS=%lu FAIL=%lu MAX_US=%lu TIMEOUT=%lu IO=%lu SCHED=%lu STALE=%lu ACTIVE=%lu ST=%lu\r\n",
                 (unsigned long)request_id, (unsigned long)dma_stats.attempts,
                 (unsigned long)dma_stats.failures, (unsigned long)dma_stats.max_elapsed_us,
                 (unsigned long)dma_stats.timeouts, (unsigned long)dma_stats.dma_errors,
                 (unsigned long)dma_stats.schedule_misses, (unsigned long)dma_stats.control_stale,
                 (unsigned long)dma_stats.periodic, (unsigned long)dma_stats.last_status);
        AsDmaFaultSnapshot dma_fault;
        AS5047P_DmaGetFaultSnapshot(&dma_fault);
        (void)Protocol_SendFormatted(msg, sizeof(msg),
                 "%lu OK ENC SNAP VALID=%lu ST=%lu PH=%lu FR=%lu START=%lu NOW=%lu DUE=%lu GUARD=%lu IPSR=%lu\r\n",
                 (unsigned long)request_id, (unsigned long)dma_fault.valid,
                 (unsigned long)dma_fault.status, (unsigned long)dma_fault.phase,
                 (unsigned long)dma_fault.frame, (unsigned long)dma_fault.started_us,
                 (unsigned long)dma_fault.now_us, (unsigned long)dma_fault.deadline_us,
                 (unsigned long)dma_fault.guard_us, (unsigned long)dma_fault.ipsr);
        (void)Protocol_SendFormatted(msg, sizeof(msg),
                 "%lu OK ENC SPI SR=0x%08lX CR1=0x%08lX CR2=0x%08lX TIM_SR=0x%08lX TIM_DIER=0x%08lX\r\n",
                 (unsigned long)request_id, (unsigned long)dma_fault.spi_sr,
                 (unsigned long)dma_fault.spi_cr1, (unsigned long)dma_fault.spi_cr2,
                 (unsigned long)dma_fault.tim_sr, (unsigned long)dma_fault.tim_dier);
        (void)Protocol_SendFormatted(msg, sizeof(msg),
                 "%lu OK ENC DMAHW ISR=0x%08lX RX_NDTR=%lu TX_NDTR=%lu RX_CCR=0x%08lX TX_CCR=0x%08lX\r\n",
                 (unsigned long)request_id, (unsigned long)dma_fault.dma_isr,
                 (unsigned long)dma_fault.rx_ndtr, (unsigned long)dma_fault.tx_ndtr,
                 (unsigned long)dma_fault.rx_ccr, (unsigned long)dma_fault.tx_ccr);
#if defined(AS5047P_DMA_IRQ_PREEMPT_ADC)
        (void)Protocol_SendFormatted(msg, sizeof(msg),
                 "%lu OK ENC IRQ VALID=%lu NOW=%lu SR=0x%08lX DIER=0x%08lX CCR2=%lu LATE_US=%lu MAX_LATE_US=%lu\r\n",
                 (unsigned long)request_id, (unsigned long)dma_fault.tim_entry_valid,
                 (unsigned long)dma_fault.tim_entry_us, (unsigned long)dma_fault.tim_entry_sr,
                 (unsigned long)dma_fault.tim_entry_dier, (unsigned long)dma_fault.tim_entry_ccr2,
                 (unsigned long)dma_fault.tim_entry_late_us,
                 (unsigned long)dma_fault.guard_max_late_us);
#endif
#endif
        uint32_t reads, failures, over_1ms, last_cycles, max_cycles;
        uint32_t stack_words, stack_samples;
        uint32_t cycles_per_us = SystemCoreClock / 1000000U;

        taskENTER_CRITICAL();
        reads = encoder_diag_reads;
        failures = encoder_diag_failures;
        over_1ms = encoder_diag_over_1ms;
        last_cycles = encoder_diag_last_cycles;
        max_cycles = encoder_diag_max_cycles;
        stack_words = motor_stack_min_words;
        stack_samples = motor_stack_samples;
        taskEXIT_CRITICAL();

        (void)Protocol_SendFormatted(msg, sizeof(msg),
                 "%lu OK ENC DIAG DWT=%u READS=%lu FAIL=%lu OVER1MS=%lu LAST_US=%lu MAX_US=%lu SAFE=%u\r\n",
                 (unsigned long)request_id,
                 (unsigned int)encoder_diag_dwt_ready,
                 (unsigned long)reads, (unsigned long)failures,
                 (unsigned long)over_1ms,
                 (unsigned long)((cycles_per_us != 0U) ? last_cycles / cycles_per_us : 0U),
                 (unsigned long)((cycles_per_us != 0U) ? max_cycles / cycles_per_us : 0U),
                 (unsigned int)analog_safe_latched);
        (void)Protocol_SendFormatted(msg, sizeof(msg),
                 "%lu OK ENC STACK VALID=%u FREE_B=%lu SAMPLES=%lu SAFE_NOW=%u\r\n",
                 (unsigned long)request_id,
                 (unsigned int)(stack_samples != 0U),
                 (unsigned long)((stack_samples != 0U) ? stack_words * sizeof(StackType_t) : 0U),
                 (unsigned long)stack_samples,
                 (unsigned int)analog_safe_latched);
    }
    else if (strcmp(cmd, "ENC SAMPLE") == 0)
    {
        uint16_t raw = 0U;
        HAL_StatusTypeDef status;
        uint32_t cycles_per_us = SystemCoreClock / 1000000U;

        if ((analog_safe_latched == 0U) ||
            (HAL_GPIO_ReadPin(DRIVER_SD_GPIO_Port, DRIVER_SD_Pin) != GPIO_PIN_RESET) ||
            ((htim1.Instance->BDTR & TIM_BDTR_MOE) != 0U) ||
            (foc_enable != 0U))
        {
            Protocol_SendError(request_id, PROTO_ERR_NOT_READY,
                               "ANALOG_SAFE_REQUIRED");
            return;
        }
        if (encoder_diag_dwt_ready == 0U)
        {
            Protocol_SendError(request_id, PROTO_ERR_NOT_READY,
                               "DWT_UNAVAILABLE");
            return;
        }

        status = AS5047P_ReadAngle(&raw);
        (void)Protocol_SendFormatted(msg, sizeof(msg),
                 "%lu OK ENC SAMPLE HAL=%u RAW=%u US=%lu SAFE=1 SD=0 MOE=0 FOC=0\r\n",
                 (unsigned long)request_id, (unsigned int)status,
                 (unsigned int)raw,
                 (unsigned long)((cycles_per_us != 0U) ? encoder_diag_last_cycles / cycles_per_us : 0U));
    }
#if defined(ESP_NETWORK_OBSERVER)
    else if (strcmp(cmd, "NET STATUS") == 0)
    {
        (void)Protocol_SendFormatted(msg, sizeof(msg), "%lu OK NET RUN=%lu SEQ=%lu DROP=%lu CONTROL=LOCKED\r\n",
                 (unsigned long)request_id, (unsigned long)g_network_run,
                 (unsigned long)g_network_seq, (unsigned long)g_network_drop);
    }
#endif
    else if (strcmp(cmd, "SELFTEST STATUS") == 0)
    {
        Protocol_PrintSelftestStatus(request_id);
    }
    else if (strcmp(cmd, "FAULT SNAPSHOT") == 0)
    {
        if (foc_current_trip_snapshot.valid == 0U)
        {
            (void)Protocol_SendFormatted(msg, sizeof(msg),
                     "%lu OK FAULT SNAPSHOT VALID=0 REASON=%lu\r\n",
                     (unsigned long)request_id,
                     (unsigned long)foc_fault_reason);
        }
        else
        {
            char snapshot_line[ROUTER_MAX_PAYLOAD + 1U];
            int n;
            ProtocolTxBuffer reply = {0};

            if (!ProtocolTxBuffer_Begin(&reply,
                    (protocol_reply_route_active == 0U && g_rtos_started != 0U &&
                     g_uart_async_runtime_enable != 0U),
                    snapshot_line, sizeof(snapshot_line), UART_PROTOCOL_TX_TIMEOUT_MS))
                return; /* Preserve failed-enqueue semantics, no unsafe fallback. */
            __DMB();
            n = snprintf(reply.data, reply.capacity,
                         "%lu OK FAULT SNAPSHOT VALID=1 REASON=1 MS=%lu SEQ=%lu "
                         "UA=%u VA=%u UP=%u VP=%u U0=%u V0=%u "
                         "IU=%ld IV=%ld IW=%ld VB=%u VAGE=%lu VVALID=%u\r\n",
                         (unsigned long)request_id,
                         (unsigned long)foc_current_trip_snapshot.tick_ms,
                         (unsigned long)foc_current_trip_snapshot.adc_seq,
                         (unsigned int)foc_current_trip_snapshot.accepted_u,
                         (unsigned int)foc_current_trip_snapshot.accepted_v,
                         (unsigned int)foc_current_trip_snapshot.physical_u,
                         (unsigned int)foc_current_trip_snapshot.physical_v,
                         (unsigned int)foc_current_trip_snapshot.zero_u,
                         (unsigned int)foc_current_trip_snapshot.zero_v,
                         (long)foc_current_trip_snapshot.iu_mA,
                         (long)foc_current_trip_snapshot.iv_mA,
                         (long)foc_current_trip_snapshot.iw_mA,
                         (unsigned int)foc_current_trip_snapshot.vbus_raw,
                         (unsigned long)foc_current_trip_snapshot.vbus_age_ms,
                         (unsigned int)foc_current_trip_snapshot.vbus_valid);
            if ((n < 0) || (n > (int)ROUTER_MAX_PAYLOAD))
            {
                ProtocolTxBuffer_Cancel(&reply);
                Protocol_SendError(request_id, PROTO_ERR_LINE_TOO_LONG,
                                   "FAULT_SNAPSHOT_TOO_LONG");
            }
            else
            {
                (void)ProtocolTxBuffer_Commit(&reply, n, Protocol_SendString);
            }
        }
    }
#if defined(FOC_CURRENT_TREND4)
#include "foc_overcurrent_shadow_protocol.inc"
#endif
    else if (strcmp(cmd, "FAULT FILTER") == 0)
    {
        if (foc_current_trip_snapshot.valid == 0U)
        {
            (void)Protocol_SendFormatted(msg, sizeof(msg),
                     "%lu OK FAULT FILTER VALID=0 REASON=%lu\r\n",
                     (unsigned long)request_id,
                     (unsigned long)foc_fault_reason);
        }
        else
        {
            char filter_line[ROUTER_MAX_PAYLOAD + 3U];
            int n;
            ProtocolTxBuffer reply = {0};

            if (!ProtocolTxBuffer_Begin(&reply,
                    (protocol_reply_route_active == 0U && g_rtos_started != 0U &&
                     g_uart_async_runtime_enable != 0U),
                    filter_line, sizeof(filter_line), UART_PROTOCOL_TX_TIMEOUT_MS))
                return; /* Preserve failed-enqueue semantics, no unsafe fallback. */
            __DMB();
            n = snprintf(reply.data, reply.capacity,
                     "%lu OK FAULT FILTER VALID=1 ON=%u MC=%u VC=%lu RC=%lu RS=%lu BAD=%ld "
                     "MU0=%u MU1=%u MU2=%u MV0=%u MV1=%u MV2=%u VS=%lu VE=%lu\r\n",
                     (unsigned long)request_id,
                     (unsigned int)foc_current_trip_snapshot.filter_on,
                     (unsigned int)foc_current_trip_snapshot.median_count,
                     (unsigned long)foc_current_trip_snapshot.current_valid_count,
                     (unsigned long)foc_current_trip_snapshot.current_reject_count,
                     (unsigned long)foc_current_trip_snapshot.current_reject_streak,
                     (long)foc_current_trip_snapshot.last_rejected_step,
                     (unsigned int)foc_current_trip_snapshot.median_u[0],
                     (unsigned int)foc_current_trip_snapshot.median_u[1],
                     (unsigned int)foc_current_trip_snapshot.median_u[2],
                     (unsigned int)foc_current_trip_snapshot.median_v[0],
                     (unsigned int)foc_current_trip_snapshot.median_v[1],
                     (unsigned int)foc_current_trip_snapshot.median_v[2],
                     (unsigned long)foc_current_trip_snapshot.analog_sample_count,
                     (unsigned long)foc_current_trip_snapshot.analog_error_count);
            if ((n < 0) || (n > (int)ROUTER_MAX_PAYLOAD))
            {
                ProtocolTxBuffer_Cancel(&reply);
                Protocol_SendError(request_id, PROTO_ERR_LINE_TOO_LONG,
                                   "FAULT_FILTER_TOO_LONG");
            }
            else
            {
                (void)ProtocolTxBuffer_Commit(&reply, n, Protocol_SendString);
            }
        }
    }
#if defined(FOC_ADC_WINDOW)
    else if (strcmp(cmd, "ADC TIMING") == 0 || strcmp(cmd, "ADC WINDOW") == 0 || strcmp(cmd, "ADC BUFFER") == 0 || strcmp(cmd, "ADC COMMIT") == 0 ||
             strcmp(cmd, "ADC SPREAD U") == 0 || strcmp(cmd, "ADC SPREAD V") == 0
#if defined(FOC_PWM_BOUNDARY_TRACE) || defined(FOC_PWM_BOUNDARY_LITE)
             || strncmp(cmd, "ADC BOUNDARY", 12U) == 0
#endif
             )
    {
        if (FocAdcTiming_Format(cmd, msg, sizeof(msg)))
            Protocol_SendTaggedLine(request_id, msg);
        else
            Protocol_SendError(request_id, PROTO_ERR_LINE_TOO_LONG, "ADC_DIAG_TOO_LONG");
    }
#endif
#if defined(FOC_PROTECTED_CLOSED_LOOP)
    else if (strncmp(cmd,"MOTOR TEST ",11U)==0
#if !defined(FOC_LATEST_ORIGINAL_FSM)
             || strcmp(cmd,"STOP")==0
#endif
             )
    {
        if (protocol_reply_route_active || !protocol_esp_ping_uart_local) {
            Protocol_SendError(request_id,PROTO_ERR_FW_STATE,"LOCAL_CONSOLE_ONLY"); return;
        }
#if defined(FOC_DQ_DECOUPLING_CANDIDATE)
        if (!DqDecoupling_Command(cmd,msg,sizeof(msg)))
#endif
#if defined(FOC_BEMF_CANDIDATE)
        if (!Bemf_Command(cmd,msg,sizeof(msg)))
#endif
        ProtectedLoop_Command(cmd,msg,sizeof(msg));
        Protocol_SendTaggedLine(request_id,msg);
    }
#endif
#if defined(FOC_CONTROL_CHAIN_RECONNECT)
    else if (strncmp(cmd, "BENCH CHAIN ", 12U) == 0)
    {
        if (protocol_reply_route_active || !protocol_esp_ping_uart_local)
        {
            Protocol_SendError(request_id, PROTO_ERR_FW_STATE, "LOCAL_CONSOLE_ONLY");
            return;
        }
        ControlChain_Command(cmd, request_id, msg, sizeof(msg));
        Protocol_SendTaggedLine(request_id, msg);
    }
#endif
#if defined(FOC_ISOLATED_CONCURRENCY)
    else if (strcmp(cmd, "BENCH RUN") == 0 || strcmp(cmd, "BENCH STOP") == 0 ||
             strcmp(cmd, "BENCH STATUS") == 0 || strcmp(cmd, "BENCH STACK") == 0 ||
             strcmp(cmd, "BENCH ZERO") == 0
#if defined(FOC_FEEDBACK_SAFETY_BINDING)
             || strcmp(cmd, "BENCH PROTECTION") == 0
             || strcmp(cmd, "BENCH PROTECTION TIMING") == 0
             || strcmp(cmd, "BENCH PROTECTION FAULT") == 0
             || strcmp(cmd, "BENCH PROTECTION TEST TIMEOUT") == 0
#endif
#if defined(FOC_ZERO_MEDIAN_COMPUTE_ONLY)
             || strcmp(cmd, "BENCH ZERO FILTER") == 0
#endif
             )
    {
        if (protocol_reply_route_active != 0U)
        {
            Protocol_SendError(request_id, PROTO_ERR_FW_STATE, "LOCAL_CONSOLE_ONLY");
            return;
        }
        if (strcmp(cmd, "BENCH RUN") == 0)
        {
#if defined(TIGHTEN_SYNTHETIC_BENCH)
            if (synthetic_busy != 0U)
            {
                Protocol_SendError(request_id, PROTO_ERR_BUSY, "SIM_BUSY");
                return;
            }
#endif
            if (BootHealth_IsCurrentTrial() != 0U || !IsolatedBench_Start(60000U))
            {
                Protocol_SendError(request_id, PROTO_ERR_FW_STATE, "ISOLATED_BENCH_REJECTED");
                return;
            }
        }
        if (strcmp(cmd, "BENCH STOP") == 0) IsolatedBench_Stop(0U);
        if (strcmp(cmd, "BENCH STACK") == 0) IsolatedBench_Stacks(msg, sizeof(msg));
#if defined(FOC_FEEDBACK_SAFETY_BINDING)
        else if (strncmp(cmd, "BENCH PROTECTION", 16U) == 0)
        {
            char protection_message[320];
            if (strcmp(cmd, "BENCH PROTECTION TEST TIMEOUT") == 0) {
                if (BootHealth_IsCurrentTrial() || !FocFeedbackBinding_TestTimeout()) {
                    Protocol_SendError(request_id, PROTO_ERR_FW_STATE, "TIMEOUT_TEST_REJECTED");
                    return;
                }
                Protocol_SendTaggedLine(request_id,
                    "OK BENCH PROTECTION TEST TIMEOUT REQUESTED=1 MOTOR_QUALIFIED=0");
                return;
            }
            if (strcmp(cmd, "BENCH PROTECTION TIMING") == 0)
                FocFeedbackBinding_TimingFormat(protection_message, sizeof(protection_message));
            else if (strcmp(cmd, "BENCH PROTECTION FAULT") == 0)
                FocFeedbackBinding_FaultFormat(protection_message, sizeof(protection_message));
            else FocFeedbackBinding_Format(protection_message, sizeof(protection_message));
            Protocol_SendTaggedLine(request_id, protection_message);
            return;
        }
#endif
        else if (strcmp(cmd, "BENCH ZERO") == 0) IsolatedZero_Format(msg, sizeof(msg));
#if defined(FOC_ZERO_MEDIAN_COMPUTE_ONLY)
        else if (strcmp(cmd, "BENCH ZERO FILTER") == 0)
        {
            char filter_message[320];
            IsolatedZero_FilterFormat(filter_message, sizeof(filter_message));
            Protocol_SendTaggedLine(request_id, filter_message);
            return;
        }
#endif
        else IsolatedBench_Format(msg, sizeof(msg));
        Protocol_SendTaggedLine(request_id, msg);
    }
#endif
#if defined(TIGHTEN_SYNTHETIC_BENCH)
    else if (strncmp(cmd, "SIM ", 4U) == 0)
    {
        Synthetic_Command(request_id, cmd, msg, sizeof(msg));
    }
#endif
    else if (strcmp(cmd, "ANALOG SAFE STATUS") == 0)
    {
        (void)Protocol_SendFormatted(msg, sizeof(msg),
                 "%lu OK ANALOG SAFE LATCHED=%u SD=%u MOE=%u FOC=%u RESET_TO_EXIT=1\r\n",
                 (unsigned long)request_id,
                 (unsigned int)analog_safe_latched,
                 (unsigned int)(HAL_GPIO_ReadPin(DRIVER_SD_GPIO_Port,
                                                DRIVER_SD_Pin) == GPIO_PIN_SET),
                 (unsigned int)((htim1.Instance->BDTR & TIM_BDTR_MOE) != 0U),
                 (unsigned int)foc_enable);
    }
    else if (strcmp(cmd, "ANALOG SAFE") == 0)
    {
#if defined(FOC_PROTECTED_CLOSED_LOOP)
        ProtectedLoop_Shutdown();
#endif
#if defined(FOC_ISOLATED_CONCURRENCY)
        IsolatedBench_Stop(0U);
#endif
        if (analog_safe_latched == 0U)
        {
            BootMetaV2_t safe_meta;

            if ((BootMeta_ReadV3(&safe_meta) == 0U) ||
                (safe_meta.confirmed_slot != APP_THIS_SLOT) ||
                (BootHealth_IsCurrentTrial() != 0U))
            {
                Protocol_SendError(request_id, PROTO_ERR_FW_STATE,
                                   "SLOT_NOT_CONFIRMED");
                return;
            }
            if ((Tightening_IsBusy() != 0U) ||
                (tightening_start_request != 0U) ||
                (motor_control_mode != MOTOR_MODE_IDLE))
            {
                Protocol_SendError(request_id, PROTO_ERR_BUSY,
                                   "MOTOR_BUSY");
                return;
            }
            if ((encoder_valid == 0U) ||
                (!isfinite(encoder_speed_rpm)) ||
                (fabsf(encoder_speed_rpm) >= ANALOG_SAFE_MAX_RPM))
            {
                Protocol_SendError(request_id, PROTO_ERR_ROTOR_MOVING,
                                   "ROTOR_NOT_STATIONARY");
                return;
            }

            /* Disable the gate before stopping the timer. No ordinary
             * command can clear this latch or re-enable the bridge. */
            PowerStage_Disable();
            foc_enable = 0U;
            analog_safe_latched = 1U;
            MotorControl_SetIdle();
            PWM_StopAll();
            __HAL_TIM_MOE_DISABLE(&htim1);
        }

        if ((HAL_GPIO_ReadPin(DRIVER_SD_GPIO_Port,
                              DRIVER_SD_Pin) != GPIO_PIN_RESET) ||
            ((htim1.Instance->BDTR & TIM_BDTR_MOE) != 0U))
        {
            Protocol_SendError(request_id, PROTO_ERR_FAULT,
                               "SAFE_OUTPUT_VERIFY_FAILED");
        }
        else
        {
            (void)Protocol_SendFormatted(msg, sizeof(msg),
                     "%lu OK ANALOG SAFE LATCHED=1 SD=0 MOE=0 FOC=0 RESET_TO_EXIT=1\r\n",
                     (unsigned long)request_id);
        }
    }
    else if (strcmp(cmd, "ANALOG BOOT") == 0)
    {
        (void)Protocol_SendFormatted(msg, sizeof(msg),
                 "%lu OK ANALOG BOOT VALID=%u PC4_RAW=%u PC5_RAW=%u ADC=ADC2 LIVE=0\r\n",
                 (unsigned long)request_id,
                 (unsigned int)analog_boot_valid,
                 (unsigned int)analog_boot_pc4_raw,
                 (unsigned int)analog_boot_pc5_raw);
    }
    else if (strcmp(cmd, "ANALOG LIVE") == 0)
    {
        uint32_t count = analog_live_sample_count;
        uint32_t age_ms = (count != 0U)
                            ? (HAL_GetTick() - analog_live_last_tick_ms)
                            : UINT32_MAX;
        uint8_t fresh = (analog_live_valid != 0U) &&
                        (age_ms <= ANALOG_LIVE_FRESH_MS);

        (void)Protocol_SendFormatted(msg, sizeof(msg),
                 "%lu OK ANALOG LIVE VALID=%u PC4_RAW=%u PC5_RAW=%u AGE_MS=%lu SAMPLES=%lu ERRORS=%lu ADC=ADC2 IDLE_ONLY=1\r\n",
                 (unsigned long)request_id,
                 (unsigned int)fresh,
                 (unsigned int)analog_live_pc4_raw,
                 (unsigned int)analog_live_pc5_raw,
                 (unsigned long)age_ms,
                 (unsigned long)count,
                 (unsigned long)analog_live_error_count);
    }
    else if (strcmp(cmd, "ANALOG VOLT") == 0)
    {
        uint32_t age_ms = (analog_live_sample_count != 0U)
                            ? (HAL_GetTick() - analog_live_last_tick_ms)
                            : UINT32_MAX;
        uint8_t valid = (analog_live_valid != 0U) &&
                        (analog_vdda_boot_valid != 0U) &&
                        (age_ms <= ANALOG_LIVE_FRESH_MS);
        uint32_t vbus_est_mv = 0U;
        uint32_t vtemp_mv = 0U;

        if (valid != 0U)
        {
            vbus_est_mv = (uint32_t)
                (((uint64_t)analog_live_pc4_raw *
                  (uint64_t)analog_vdda_boot_mv *
                  ANALOG_VBUS_DIVIDER + (ADC_FULL_SCALE / 2U)) /
                 ADC_FULL_SCALE);
            vtemp_mv = (uint32_t)
                (((uint64_t)analog_live_pc5_raw *
                  (uint64_t)analog_vdda_boot_mv +
                  (ADC_FULL_SCALE / 2U)) /
                 ADC_FULL_SCALE);
        }

        (void)Protocol_SendFormatted(msg, sizeof(msg),
                 "%lu OK ANALOG VOLT VALID=%u VBUS_EST_MV=%lu VTEMP_MV=%lu VDDA_BOOT_MV=%u VREF_RAW=%u AGE_MS=%lu DIV=25 PROTECT=0\r\n",
                 (unsigned long)request_id,
                 (unsigned int)valid,
                 (unsigned long)vbus_est_mv,
                 (unsigned long)vtemp_mv,
                 (unsigned int)analog_vdda_boot_mv,
                 (unsigned int)analog_vref_boot_raw,
                 (unsigned long)age_ms);
    }
    else if (strcmp(cmd, "ANALOG PAIR") == 0)
    {
        AnalogPairDiag_t pair;

        taskENTER_CRITICAL();
        pair = analog_pair_diag;
        taskEXIT_CRITICAL();
        (void)Protocol_SendFormatted(msg, sizeof(msg),
                 "%lu OK ANALOG PAIR VALID=%u LATCHED=%u LAST1=%u LAST2=%u "
                 "PEAK1=%u PEAK1_2=%u PEAK2=%u PEAK2_1=%u COUNT=%lu ERR=%lu "
                 "ADC=ADC2 PC4=CH5 PROTECT=0\r\n",
                 (unsigned long)request_id,
                 (unsigned int)(pair.count != 0U),
                 (unsigned int)analog_safe_latched,
                 (unsigned int)pair.last_first,
                 (unsigned int)pair.last_second,
                 (unsigned int)pair.peak_first,
                 (unsigned int)pair.peak_first_second,
                 (unsigned int)pair.peak_second,
                 (unsigned int)pair.peak_second_first,
                 (unsigned long)pair.count,
                 (unsigned long)pair.errors);
    }
    else if ((strcmp(cmd, "ANALOG TRIPLE") == 0) ||
             (strcmp(cmd, "ANALOG PC5 TRIPLE") == 0))
    {
        AnalogTripleDiag_t triple;
        uint8_t pc5_selected = (strcmp(cmd, "ANALOG PC5 TRIPLE") == 0);
        uint32_t age_ms;
        uint8_t valid;
        uint32_t median_mv = 0U;

        taskENTER_CRITICAL();
        triple = (pc5_selected != 0U) ? analog_pc5_triple_diag : analog_triple_diag;
        taskEXIT_CRITICAL();
        age_ms = (triple.count != 0U)
                     ? (HAL_GetTick() - triple.last_tick_ms)
                     : UINT32_MAX;
        valid = (analog_safe_latched != 0U) &&
                (analog_vdda_boot_valid != 0U) &&
                (triple.count != 0U) &&
                (age_ms <= ANALOG_LIVE_FRESH_MS);
        if (valid != 0U)
        {
            median_mv = (uint32_t)
                (((uint64_t)triple.last_median *
                  (uint64_t)analog_vdda_boot_mv *
                  (pc5_selected != 0U ? 1U : ANALOG_VBUS_DIVIDER) +
                  (ADC_FULL_SCALE / 2U)) /
                 ADC_FULL_SCALE);
        }
        (void)Protocol_SendFormatted(msg, sizeof(msg),
                 "%lu OK ANALOG %sTRIPLE V=%u R=%u,%u,%u M=%u MV=%lu "
                 "PR=%u,%u,%u PM=%u,%u,%u SP=%u D=%lu N=%lu E=%lu\r\n",
                 (unsigned long)request_id,
                 (pc5_selected != 0U) ? "PC5 " : "",
                 (unsigned int)valid,
                 (unsigned int)triple.last_first,
                 (unsigned int)triple.last_second,
                 (unsigned int)triple.last_third,
                 (unsigned int)triple.last_median,
                 (unsigned long)median_mv,
                 (unsigned int)triple.peak_raw_first,
                 (unsigned int)triple.peak_raw_second,
                 (unsigned int)triple.peak_raw_third,
                 (unsigned int)triple.peak_median_first,
                 (unsigned int)triple.peak_median_second,
                 (unsigned int)triple.peak_median_third,
                 (unsigned int)triple.max_spread,
                 (unsigned long)triple.disagree_count,
                 (unsigned long)triple.count,
                 (unsigned long)triple.errors);
    }
    else if (strcmp(cmd, "KVS STATUS") == 0)
    {
        PW_KvsDiagnostics_t diagnostics;

        PW_Kvs_GetDiagnostics(&diagnostics);
        (void)Protocol_SendFormatted(
            msg,
            sizeof(msg),
            "%lu OK KVS READY=%lu ENTRIES=%lu TXN=%lu REDUNDANCY=%lu WRITABLE=%lu INUSE=%lu RECLAIM=%lu ERASES=%lu\r\n",
            (unsigned long)request_id,
            (unsigned long)diagnostics.initialized,
            (unsigned long)diagnostics.entries,
            (unsigned long)diagnostics.transaction_count,
            (unsigned long)diagnostics.redundancy,
            (unsigned long)diagnostics.writable_bytes,
            (unsigned long)diagnostics.in_use_bytes,
            (unsigned long)diagnostics.reclaimable_bytes,
            (unsigned long)diagnostics.sector_erase_count);
    }
    else if ((strcmp(cmd, "ALLOC STATUS") == 0) ||
             (strcmp(cmd, "ALLOC TEST") == 0))
    {
        PW_AllocatorDiagnostics_t diagnostics;

        if (strcmp(cmd, "ALLOC TEST") == 0)
        {
            (void)PW_Allocator_RunSelfTest();
        }
        PW_Allocator_GetDiagnostics(&diagnostics);
        (void)Protocol_SendFormatted(
            msg,
            sizeof(msg),
            "%lu OK ALLOC BACKEND=FREERTOS_HEAP4 FREE=%lu MIN=%lu PASS=%lu ALLOCS=%lu BEFORE=%lu LOW=%lu AFTER=%lu ISR=FORBIDDEN HYBRID=%lu LIVE=%lu OBJECTS=%lu PEAK=%lu FAIL=%lu CTX=%lu UART=%lu LOGINDEX=%lu TEMP=%lu\r\n",
            (unsigned long)request_id,
            (unsigned long)diagnostics.free_bytes,
            (unsigned long)diagnostics.minimum_ever_free_bytes,
            (unsigned long)diagnostics.last_test_passed,
            (unsigned long)diagnostics.last_test_allocations,
            (unsigned long)diagnostics.last_test_before_bytes,
            (unsigned long)diagnostics.last_test_low_bytes,
            (unsigned long)diagnostics.last_test_after_bytes,
            (unsigned long)diagnostics.hybrid_enabled,
            (unsigned long)diagnostics.managed.live_bytes,
            (unsigned long)diagnostics.managed.live_objects,
            (unsigned long)diagnostics.managed.peak_bytes,
            (unsigned long)diagnostics.managed.allocation_failures,
            (unsigned long)diagnostics.managed.context_rejections,
            (unsigned long)diagnostics.managed.tag_bytes[PW_BUFFER_UART],
            (unsigned long)diagnostics.managed.tag_bytes[PW_BUFFER_LOG_SNAPSHOT],
            (unsigned long)diagnostics.managed.tag_bytes[PW_BUFFER_TEMP]);
    }
    else if (strcmp(cmd, "LOG STATUS") == 0)
    {
        PW_LogDiagnostics_t diagnostics;

        PW_Log_GetDiagnostics(&diagnostics);
        (void)Protocol_SendFormatted(
            msg,
            sizeof(msg),
            "%lu OK LOG READY=%lu LEVEL=%s QUEUED=%lu CAP=%lu HIST=%lu SEQ=%lu ENQ=%lu SENT=%lu DROP_FULL=%lu DROP_UART=%lu DROP_ISR=%lu FILTERED=%lu HIGH_WATER=%lu TOK=%lu TBIN=%lu TB64=%lu\r\n",
            (unsigned long)request_id,
            (unsigned long)diagnostics.ready,
            PW_Log_LevelName((int)diagnostics.level),
            (unsigned long)diagnostics.queued,
            (unsigned long)diagnostics.capacity,
            (unsigned long)diagnostics.history_count,
            (unsigned long)diagnostics.sequence,
            (unsigned long)diagnostics.enqueued,
            (unsigned long)diagnostics.sent,
            (unsigned long)diagnostics.dropped_full,
            (unsigned long)diagnostics.dropped_uart,
            (unsigned long)diagnostics.dropped_isr,
            (unsigned long)diagnostics.filtered,
            (unsigned long)diagnostics.high_water,
            (unsigned long)diagnostics.tokenized,
            (unsigned long)diagnostics.token_binary_bytes,
            (unsigned long)diagnostics.token_base64_bytes);
    }
    else if (strcmp(cmd, "LOG ROUTER STATUS") == 0)
    {
        PW_LogRouterDiagnostics_t diagnostics;

        PW_LogRouter_GetDiagnostics(&diagnostics);
        (void)Protocol_SendFormatted(msg,
                 sizeof(msg),
                 "%lu OK LOG ROUTER READY=%lu SUBS=%lu QUEUED=%lu CAP=%lu CAPTURED=%lu DROP=%lu SENT=%lu ROUTE_FAIL=%lu LEVEL_FILTER=%lu EXPIRED=%lu REMOTE_RX=%lu TYPE=%u\r\n",
                 (unsigned long)request_id,
                 (unsigned long)diagnostics.ready,
                 (unsigned long)diagnostics.subscribers,
                 (unsigned long)diagnostics.queued,
                 (unsigned long)diagnostics.queue_capacity,
                 (unsigned long)diagnostics.captured,
                 (unsigned long)diagnostics.queue_dropped,
                 (unsigned long)diagnostics.routed_sent,
                 (unsigned long)diagnostics.route_failed,
                 (unsigned long)diagnostics.level_filtered,
                 (unsigned long)diagnostics.expired,
                 (unsigned long)diagnostics.remote_received,
                 (unsigned int)PW_LOG_ROUTER_PACKET_TYPE);
    }
    else if (strcmp(cmd, "LOG SUBSCRIBERS") == 0)
    {
        PW_LogRouterDiagnostics_t diagnostics;
        uint32_t i;

        PW_LogRouter_GetDiagnostics(&diagnostics);
        (void)Protocol_SendFormatted(msg, sizeof(msg), "%lu OK LOG SUBSCRIBERS COUNT=%lu\r\n",
                 (unsigned long)request_id,
                 (unsigned long)diagnostics.subscribers);
        for (i = 0U; i < diagnostics.subscribers; i++)
        {
            PW_LogRouterSubscriber_t subscriber;
            if (PW_LogRouter_GetSubscriber(i, &subscriber) != 0)
            {
                (void)Protocol_SendFormatted(msg, sizeof(msg),
                         "%lu LOG SUB NODE=%u LEVEL=%s REMAIN_MS=%lu\r\n",
                         (unsigned long)request_id,
                         (unsigned int)subscriber.node_id,
                         PW_Log_LevelName((int)subscriber.min_level),
                         (unsigned long)subscriber.remaining_ms);
            }
        }
        Protocol_SendTaggedLine(request_id, "OK LOG SUBSCRIBERS END");
    }
    else if (strncmp(cmd, "LOG SUBSCRIBE ", 14U) == 0)
    {
        unsigned long node = 0UL;
        unsigned long seconds = 0UL;
        char level_text[16] = {0};
        char extra;
        int fields;
        int level = 0;

        if (protocol_reply_route_active != 0U)
        {
            node = protocol_reply_route_dst;
            fields = sscanf(cmd + 14U, "%15s %lu %c",
                            level_text, &seconds, &extra);
            fields = (fields == 2) ? 3 : 0;
        }
        else
        {
            fields = sscanf(cmd + 14U, "%lu %15s %lu %c",
                            &node, level_text, &seconds, &extra);
        }

        if (strcmp(level_text, "DEBUG") == 0) level = PW_LOG_RUNTIME_DEBUG;
        else if (strcmp(level_text, "INFO") == 0) level = PW_LOG_RUNTIME_INFO;
        else if (strcmp(level_text, "WARN") == 0) level = PW_LOG_RUNTIME_WARN;
        else if (strcmp(level_text, "ERROR") == 0) level = PW_LOG_RUNTIME_ERROR;
        else if (strcmp(level_text, "CRITICAL") == 0) level = PW_LOG_RUNTIME_CRITICAL;
        else if (strcmp(level_text, "FATAL") == 0) level = PW_LOG_RUNTIME_FATAL;

        if ((fields != 3) || (node > 0xFFFEUL) ||
            (level == 0) || (seconds == 0UL) || (seconds > 3600UL) ||
            (PW_LogRouter_Subscribe((uint16_t)node, level,
                                    (uint32_t)seconds) == 0))
        {
            Protocol_SendError(request_id, PROTO_ERR_BAD_ARGUMENT, "LOG_SUBSCRIBE");
        }
        else
        {
            (void)Protocol_SendFormatted(msg, sizeof(msg),
                     "%lu OK LOG SUBSCRIBE NODE=%lu LEVEL=%s TTL=%lus TYPE=%u\r\n",
                     (unsigned long)request_id,
                     node,
                     PW_Log_LevelName(level),
                     seconds,
                     (unsigned int)PW_LOG_ROUTER_PACKET_TYPE);
        }
    }
    else if ((strcmp(cmd, "LOG UNSUBSCRIBE") == 0) ||
             (strncmp(cmd, "LOG UNSUBSCRIBE ", 16U) == 0))
    {
        unsigned long node = 0UL;
        char extra;
        int valid = 0;

        if ((protocol_reply_route_active != 0U) &&
            (strcmp(cmd, "LOG UNSUBSCRIBE") == 0))
        {
            node = protocol_reply_route_dst;
            valid = 1;
        }
        else if ((protocol_reply_route_active == 0U) &&
                 (sscanf(cmd + 16U, "%lu %c", &node, &extra) == 1) &&
                 (node <= 0xFFFEUL))
        {
            valid = 1;
        }

        if ((valid == 0) || (PW_LogRouter_Unsubscribe((uint16_t)node) == 0))
        {
            Protocol_SendError(request_id, PROTO_ERR_BAD_ARGUMENT, "LOG_UNSUBSCRIBE");
        }
        else
        {
            (void)Protocol_SendFormatted(msg, sizeof(msg), "%lu OK LOG UNSUBSCRIBE NODE=%lu\r\n",
                     (unsigned long)request_id, node);
        }
    }
    else if (strcmp(cmd, "LOG DUMP") == 0)
    {
        uint32_t dumped;

        Protocol_SendTaggedLine(request_id, "OK LOG DUMP BEGIN");
        dumped = PW_Log_Dump();
        (void)Protocol_SendFormatted(msg,
                 sizeof(msg),
                 "%lu OK LOG DUMP END SENT=%lu\r\n",
                 (unsigned long)request_id,
                 (unsigned long)dumped);
    }
    else if (strcmp(cmd, "LOG CLEAR") == 0)
    {
        PW_Log_Clear();
        Protocol_SendTaggedLine(request_id, "OK LOG CLEARED");
    }
    else if (strncmp(cmd, "LOG LEVEL ", 10U) == 0)
    {
        int level = 0;
        const char *level_text = cmd + 10U;

        if (strcmp(level_text, "DEBUG") == 0) level = PW_LOG_RUNTIME_DEBUG;
        else if (strcmp(level_text, "INFO") == 0) level = PW_LOG_RUNTIME_INFO;
        else if (strcmp(level_text, "WARN") == 0) level = PW_LOG_RUNTIME_WARN;
        else if (strcmp(level_text, "ERROR") == 0) level = PW_LOG_RUNTIME_ERROR;
        else if (strcmp(level_text, "CRITICAL") == 0) level = PW_LOG_RUNTIME_CRITICAL;
        else if (strcmp(level_text, "FATAL") == 0) level = PW_LOG_RUNTIME_FATAL;

        if ((level == 0) || (PW_Log_SetLevel(level) == 0))
        {
            Protocol_SendError(request_id, PROTO_ERR_BAD_ARGUMENT, "LOG_LEVEL");
        }
        else
        {
            (void)Protocol_SendFormatted(msg,
                     sizeof(msg),
                     "%lu OK LOG LEVEL=%s\r\n",
                     (unsigned long)request_id,
                     PW_Log_LevelName(level));
        }
    }
    else if (strncmp(cmd, "LOG TEST ", 9U) == 0)
    {
        char *test_end;
        unsigned long requested = strtoul(cmd + 9U, &test_end, 10);

        if ((test_end == (cmd + 9U)) || (*test_end != '\0') ||
            (requested == 0UL) || (requested > 1000UL))
        {
            Protocol_SendError(request_id, PROTO_ERR_BAD_ARGUMENT, "LOG_TEST_COUNT");
        }
        else
        {
            uint32_t accepted = PW_Log_TestBurst((uint32_t)requested);
            (void)Protocol_SendFormatted(msg,
                     sizeof(msg),
                     "%lu OK LOG TEST REQUESTED=%lu ACCEPTED=%lu NOT_ENQUEUED=%lu\r\n",
                     (unsigned long)request_id,
                     requested,
                     (unsigned long)accepted,
                     (unsigned long)((uint32_t)requested - accepted));
        }
    }
    else if (strncmp(cmd, "LOG TOKEN TEST ", 15U) == 0)
    {
        char *test_end;
        unsigned long requested = strtoul(cmd + 15U, &test_end, 10);

        if ((test_end == (cmd + 15U)) || (*test_end != '\0') ||
            (requested == 0UL) || (requested > 1000UL))
        {
            Protocol_SendError(request_id, PROTO_ERR_BAD_ARGUMENT, "LOG_TOKEN_COUNT");
        }
        else
        {
            uint32_t accepted = PW_Log_TokenizedTestBurst((uint32_t)requested);
            (void)Protocol_SendFormatted(msg,
                     sizeof(msg),
                     "%lu OK LOG TOKEN TEST REQUESTED=%lu ACCEPTED=%lu NOT_ENQUEUED=%lu FORMAT=PWT_BASE64\r\n",
                     (unsigned long)request_id,
                     requested,
                     (unsigned long)accepted,
                     (unsigned long)((uint32_t)requested - accepted));
        }
    }
    else if (strncmp(cmd, "RPC ", 4U) == 0)
    {
        PW_Rpc_HandleCommand(request_id, cmd + 4U);
    }
    else if (strncmp(cmd, "XFER ", 5U) == 0)
    {
#if defined(UART_FIRMWARE_TRANSFER)
        if (strncmp(cmd, "XFER ENGINE ", 12U) == 0)
            UartFirmwareTransfer_Command(request_id, cmd + 12U);
        else
#endif
        PW_Transfer_HandleCommand(request_id, cmd + 5U);
    }
    else if (strcmp(cmd, "BOOT STATUS") == 0)
    {
        BootMetaV2_t meta;

        if (BootMeta_ReadV3(&meta) != 0U)
        {
            (void)Protocol_SendFormatted(
                msg,
                sizeof(msg),
                "%lu OK BOOT V=3 CONFIRMED=%c PENDING=%c ATTEMPTS=%lu GEN=%lu\r\n",
                (unsigned long)request_id,
                (meta.confirmed_slot == BOOT_SLOT_A) ? 'A' : 'B',
                (meta.pending_slot == BOOT_SLOT_A) ? 'A' :
                (meta.pending_slot == BOOT_SLOT_B) ? 'B' : '-',
                (unsigned long)meta.attempts_left,
                (unsigned long)meta.generation);
        }
        else
        {
            BootMetaV1_t old_meta;

            if (BootMeta_ReadV1(&old_meta) != 0U)
            {
                (void)Protocol_SendFormatted(
                    msg,
                    sizeof(msg),
                    "%lu OK BOOT V=1 ACTIVE=%c\r\n",
                    (unsigned long)request_id,
                    (old_meta.active_slot == BOOT_SLOT_A) ? 'A' : 'B');
            }
            else
            {
                (void)Protocol_SendFormatted(
                    msg,
                    sizeof(msg),
                    "%lu OK BOOT META_VALID=0 DEFAULT=A\r\n",
                    (unsigned long)request_id);
            }
        }
    }
    else if ((strcmp(cmd, "BOOT A") == 0) ||
             (strcmp(cmd, "BOOT B") == 0))
    {
        uint32_t slot =
            (strcmp(cmd, "BOOT A") == 0) ?
            BOOT_SLOT_A :
            BOOT_SLOT_B;

        if (BootHealth_IsCurrentTrial() != 0U)
        {
            Protocol_SendError(
                request_id,
                PROTO_ERR_FW_STATE,
                "TRIAL_NOT_CONFIRMED");
        }
        else if ((fw_update.active != 0U) ||
                 (Tightening_IsBusy() != 0U) ||
                 (tightening_start_request != 0U) ||
                 (motor_control_mode != MOTOR_MODE_IDLE))
        {
            Protocol_SendError(
                request_id,
                PROTO_ERR_BUSY,
                "BUSY");
        }
        else if (fabsf(encoder_speed_rpm) > 2.0f)
        {
            Protocol_SendError(
                request_id,
                PROTO_ERR_ROTOR_MOVING,
                "ROTOR_MOVING");
        }
        else if (BootMeta_SaveSlot(slot) == 0U)
        {
            Protocol_SendError(
                request_id,
                PROTO_ERR_FLASH,
                "MAILBOX_ERROR");
        }
        else
        {
            (void)Protocol_SendFormatted(
                msg,
                sizeof(msg),
                "%lu OK BOOT SLOT=%c REQUESTED RESETTING\r\n",
                (unsigned long)request_id,
                (slot == BOOT_SLOT_A) ? 'A' : 'B');

            vTaskDelay(pdMS_TO_TICKS(100U));
            NVIC_SystemReset();
        }
    }
    else if (strcmp(cmd, "FW STATUS") == 0)
    {
        Fw_SendStatus(request_id);
    }
    else if (strcmp(cmd, "FW CONFIRM") == 0)
    {
        if (fw_update.active != 0U)
        {
            Protocol_SendError(
                request_id,
                PROTO_ERR_FW_STATE,
                "FW_UPDATE_ACTIVE");
        }
        else if (BootMeta_ConfirmCurrent() == 0U)
        {
            Protocol_SendError(
                request_id,
                PROTO_ERR_FLASH,
                "MAILBOX_ERROR");
        }
        else
        {
            (void)Protocol_SendFormatted(
                msg,
                sizeof(msg),
                "%lu OK FW CONFIRM REQUESTED SLOT=%c RESETTING\r\n",
                (unsigned long)request_id,
                (APP_THIS_SLOT == BOOT_SLOT_A) ? 'A' : 'B');

            Fw_EnterSafeState();
            vTaskDelay(pdMS_TO_TICKS(100U));
            NVIC_SystemReset();
        }
    }
    else if (strncmp(cmd, "FW BEGIN ", 9U) == 0)
    {
#if defined(TIGHTEN_SYNTHETIC_BENCH)
        if (synthetic_busy != 0U)
        {
            Protocol_SendError(request_id, PROTO_ERR_BUSY, "SIM_BUSY");
            return;
        }
#endif
        char *size_text;
        char *crc_text;
        char *end_size;
        char *end_crc;
        unsigned long image_size_ul;
        unsigned long image_crc_ul;
        BootMetaV2_t meta;
        uint8_t ack_queued;

        g_fw_diag_stage = 10U;
        g_fw_diag_ack_queued = 0U;
        g_fw_diag_hal_status = 0U;
        g_fw_diag_lock_status = 0U;
        g_fw_diag_page_error = 0xFFFFFFFFUL;
        g_fw_diag_flash_error = 0U;
        g_fw_diag_flash_sr = FLASH->SR;
        g_fw_diag_flash_cr = FLASH->CR;
        Fw_DiagSnapshotComms();

        if (BootHealth_IsCurrentTrial() != 0U)
        {
            Protocol_SendError(request_id, PROTO_ERR_FW_STATE, "TRIAL_NOT_CONFIRMED");
        }
        else if ((fw_update.active != 0U) ||
                 (Tightening_IsBusy() != 0U) ||
                 (tightening_start_request != 0U) ||
                 (motor_control_mode != MOTOR_MODE_IDLE))
        {
            Protocol_SendError(request_id, PROTO_ERR_BUSY, "BUSY");
        }
        else if (fabsf(encoder_speed_rpm) > 2.0f)
        {
            Protocol_SendError(request_id, PROTO_ERR_ROTOR_MOVING, "ROTOR_MOVING");
        }
        else if ((adc_fault != 0U) || (foc_fault != 0U))
        {
            Protocol_SendError(request_id, PROTO_ERR_FAULT, "FAULT");
        }
        else
        {
            size_text = cmd + 9U;
            while ((*size_text == ' ') || (*size_text == '\t'))
            {
                size_text++;
            }

            image_size_ul = strtoul(size_text, &end_size, 10);

            while ((*end_size == ' ') || (*end_size == '\t'))
            {
                end_size++;
            }

            crc_text = end_size;
            image_crc_ul = strtoul(crc_text, &end_crc, 16);

            while ((*end_crc == ' ') || (*end_crc == '\t'))
            {
                end_crc++;
            }

            if ((size_text == end_size) ||
                (crc_text == end_crc) ||
                (*end_crc != '\0') ||
                (image_size_ul < 8UL) ||
                (image_size_ul > FW_SLOT_SIZE) ||
                (image_crc_ul > 0xFFFFFFFFUL))
            {
                Protocol_SendError(request_id, PROTO_ERR_BAD_ARGUMENT, "BAD_FW_BEGIN");
            }
            else if ((BootMeta_ReadV3(&meta) != 0U) &&
                     (meta.pending_slot == APP_THIS_SLOT) &&
                     (meta.confirmed_slot != APP_THIS_SLOT))
            {
                Protocol_SendError(request_id, PROTO_ERR_FW_STATE, "CURRENT_SLOT_NOT_CONFIRMED");
            }
            else
            {
                g_fw_diag_stage = 20U;
                Fw_DiagSnapshotComms();

                g_fw_diag_stage = 30U;
                Fw_EnterSafeState();
                g_fw_diag_stage = 40U;

                /* Build the update context while keeping ACTIVE=0 until the
                   target slot has actually been erased successfully. */
                Fw_ResetContext();
                fw_update.image_size = (uint32_t)image_size_ul;
                fw_update.expected_crc32 = (uint32_t)image_crc_ul;

                if (Fw_EraseTarget(fw_update.image_size) == 0U)
                {
                    Fw_ResetContext();
                    Protocol_SendError(request_id, PROTO_ERR_FLASH, "ERASE_FAILED");
                }
                else
                {
                    fw_update.active = 1U;
                    g_fw_diag_stage = 100U;
                    Fw_DiagSnapshotComms();

                    ack_queued = Protocol_SendFormatted(
                        msg,
                        sizeof(msg),
                        "%lu OK FW BEGIN TARGET=%c SIZE=%lu CRC32=0x%08lX\r\n",
                        (unsigned long)request_id,
                        (APP_TARGET_SLOT == BOOT_SLOT_A) ? 'A' : 'B',
                        (unsigned long)fw_update.image_size,
                        (unsigned long)fw_update.expected_crc32);
                    g_fw_diag_ack_queued = (uint32_t)ack_queued;

                    if (ack_queued != 0U)
                    {
                        g_fw_diag_stage = 110U;
                    }
                    else
                    {
                        /* Erase succeeded, but the host was not told. Leave
                           no ACTIVE half-session; a later BEGIN may safely
                           erase the inactive slot again and restart. */
                        Fw_ResetContext();
                    }

                    g_fw_diag_stage = 120U;
                    Fw_DiagSnapshotComms();
                }
            }
        }
    }
    else if (strncmp(cmd, "FW DATA ", 8U) == 0)
    {
        char *offset_text;
        char *hex_text;
        char *end_offset;
        unsigned long offset_ul;
        uint8_t data[FW_DATA_MAX_BYTES];
        uint32_t data_len = 0U;

        if (fw_update.active == 0U)
        {
            Protocol_SendError(
                request_id,
                PROTO_ERR_FW_STATE,
                "FW_NOT_ACTIVE");
        }
        else
        {
            offset_text = cmd + 8U;
            while ((*offset_text == ' ') || (*offset_text == '\t'))
            {
                offset_text++;
            }

            offset_ul = strtoul(offset_text, &end_offset, 16);

            while ((*end_offset == ' ') || (*end_offset == '\t'))
            {
                end_offset++;
            }

            hex_text = end_offset;

            if ((offset_text == end_offset) ||
                (offset_ul > 0xFFFFFFFFUL) ||
                (Fw_ParseHexBytes(hex_text, data, &data_len) == 0U))
            {
                Protocol_SendError(
                    request_id,
                    PROTO_ERR_BAD_ARGUMENT,
                    "BAD_FW_DATA");
            }
            else if ((uint32_t)offset_ul != fw_update.bytes_received)
            {
                (void)Protocol_SendFormatted(
                    msg,
                    sizeof(msg),
                    "%lu ERR %u FW_SEQUENCE EXPECT_OFFSET=%08lX\r\n",
                    (unsigned long)request_id,
                    (unsigned int)PROTO_ERR_FW_SEQUENCE,
                    (unsigned long)fw_update.bytes_received);
            }
            else if (Fw_ProgramData(
                         (uint32_t)offset_ul,
                         data,
                         data_len) == 0U)
            {
                Protocol_SendError(
                    request_id,
                    PROTO_ERR_FLASH,
                    "PROGRAM_FAILED");
            }
            else
            {
                (void)Protocol_SendFormatted(
                    msg,
                    sizeof(msg),
                    "%lu OK FW DATA OFFSET=%08lX LEN=%lu RX=%lu/%lu\r\n",
                    (unsigned long)request_id,
                    (unsigned long)offset_ul,
                    (unsigned long)data_len,
                    (unsigned long)fw_update.bytes_received,
                    (unsigned long)fw_update.image_size);
            }
        }
    }
    else if (strcmp(cmd, "FW END") == 0)
    {
        uint32_t actual_crc;
        BootMetaV2_t meta;

        if (fw_update.active == 0U)
        {
            Protocol_SendError(
                request_id,
                PROTO_ERR_FW_STATE,
                "FW_NOT_ACTIVE");
        }
        else if (fw_update.bytes_received != fw_update.image_size)
        {
            (void)Protocol_SendFormatted(
                msg,
                sizeof(msg),
                "%lu ERR %u FW_INCOMPLETE RX=%lu SIZE=%lu\r\n",
                (unsigned long)request_id,
                (unsigned int)PROTO_ERR_FW_SEQUENCE,
                (unsigned long)fw_update.bytes_received,
                (unsigned long)fw_update.image_size);
        }
        else if (Fw_TargetVectorValid() == 0U)
        {
            Protocol_SendError(
                request_id,
                PROTO_ERR_FW_RANGE,
                "BAD_TARGET_VECTOR");
        }
        else
        {
            actual_crc = Fw_TargetCrc32(fw_update.image_size);

            if (actual_crc != fw_update.expected_crc32)
            {
                (void)Protocol_SendFormatted(
                    msg,
                    sizeof(msg),
                    "%lu ERR %u FW_CRC EXPECT=0x%08lX ACTUAL=0x%08lX\r\n",
                    (unsigned long)request_id,
                    (unsigned int)PROTO_ERR_FW_CRC,
                    (unsigned long)fw_update.expected_crc32,
                    (unsigned long)actual_crc);
            }
            else if (BootMailbox_RequestStartTrial(
                         APP_TARGET_SLOT,
                         fw_update.image_size,
                         actual_crc) == 0U)
            {
                Protocol_SendError(
                    request_id,
                    PROTO_ERR_FLASH,
                    "MAILBOX_ERROR");
            }
            else
            {
                (void)Protocol_SendFormatted(
                    msg,
                    sizeof(msg),
                    "%lu OK FW END TARGET=%c SIZE=%lu CRC32=0x%08lX "
                    "COMMIT=BOOTLOADER ATTEMPTS=%lu RESETTING\r\n",
                    (unsigned long)request_id,
                    (APP_TARGET_SLOT == BOOT_SLOT_A) ? 'A' : 'B',
                    (unsigned long)fw_update.image_size,
                    (unsigned long)actual_crc,
                    (unsigned long)FW_TRIAL_ATTEMPTS);

                Fw_EnterSafeState();
                vTaskDelay(pdMS_TO_TICKS(150U));
                NVIC_SystemReset();
            }
        }
    }
    else if (strcmp(cmd, "FW ABORT") == 0)
    {
        if (fw_update.active == 0U)
        {
            Protocol_SendError(
                request_id,
                PROTO_ERR_FW_STATE,
                "FW_NOT_ACTIVE");
        }
        else
        {
            Fw_ResetContext();

            (void)Protocol_SendFormatted(
                msg,
                sizeof(msg),
                "%lu OK FW ABORTED RESETTING\r\n",
                (unsigned long)request_id);

            vTaskDelay(pdMS_TO_TICKS(100U));
            NVIC_SystemReset();
        }
    }
    else if (strcmp(cmd, "SAVE PARAMS") == 0)
    {
        if ((Tightening_IsBusy() != 0U) ||
            (tightening_start_request != 0U) ||
            (motor_control_mode != MOTOR_MODE_IDLE))
        {
            Protocol_SendError(request_id, PROTO_ERR_BUSY, "BUSY");
        }
        else if (fabsf(encoder_speed_rpm) > 2.0f)
        {
            Protocol_SendError(request_id, PROTO_ERR_ROTOR_MOVING, "ROTOR_MOVING");
        }
        else if (TightenParams_SaveToFlash() == 0U)
        {
            Protocol_SendError(request_id, PROTO_ERR_FLASH, "FLASH_ERROR");
        }
        else
        {
            (void)Protocol_SendFormatted(msg, sizeof(msg),
                     "%lu OK SAVE PARAMS CRC32=0x%08lX\r\n",
                     (unsigned long)request_id,
                     (unsigned long)recipe_state.last_crc32);
        }
    }
    else if (strcmp(cmd, "LOAD PARAMS") == 0)
    {
        TightenParamsFlashLoadStatus_t load_status;

        if ((Tightening_IsBusy() != 0U) ||
            (tightening_start_request != 0U))
        {
            Protocol_SendError(request_id, PROTO_ERR_BUSY, "BUSY");
        }
        else
        {
            load_status = TightenParams_LoadFromFlash();

            if (load_status == PARAM_FLASH_LOAD_OK)
            {
                (void)Protocol_SendFormatted(msg, sizeof(msg),
                         "%lu OK LOAD PARAMS CRC32=0x%08lX\r\n",
                         (unsigned long)request_id,
                         (unsigned long)recipe_state.last_crc32);
            }
            else
            {
                Protocol_SendError(request_id,
                                   PROTO_ERR_NO_VALID_PARAMS,
                                   "NO_VALID_PARAMS");
            }
        }
    }
    else if (strcmp(cmd, "DEFAULT PARAMS") == 0)
    {
        if ((Tightening_IsBusy() != 0U) ||
            (tightening_start_request != 0U))
        {
            Protocol_SendError(request_id, PROTO_ERR_BUSY, "BUSY");
        }
        else
        {
            TightenParams_RestoreDefaults();
            (void)Protocol_SendFormatted(msg, sizeof(msg),
                     "%lu OK DEFAULT PARAMS DIRTY=1\r\n",
                     (unsigned long)request_id);
        }
    }
    else if (strcmp(cmd, "GET PARAMS") == 0)
    {
        TightenParams_PrintAll(request_id);
    }
    else if (strncmp(cmd, "GET ", 4U) == 0)
    {
        arg = cmd + 4U;
        while ((*arg == ' ') || (*arg == '\t'))
        {
            arg++;
        }

        if (*arg == '\0')
        {
            Protocol_SendError(
                request_id,
                PROTO_ERR_BAD_ARGUMENT,
                "MISSING_PARAM");
        }
        else
        {
            (void)TightenParams_GetOne(
                request_id,
                arg);
        }
    }
    else if (strncmp(cmd, "SET ", 4U) == 0)
    {
        arg = cmd + 4U;
        while ((*arg == ' ') || (*arg == '\t'))
        {
            arg++;
        }

        value_text = arg;
        while ((*value_text != '\0') &&
               (*value_text != ' ') &&
               (*value_text != '\t'))
        {
            value_text++;
        }

        if (*value_text == '\0')
        {
            Protocol_SendError(
                request_id,
                PROTO_ERR_BAD_ARGUMENT,
                "MISSING_VALUE");
        }
        else
        {
            *value_text = '\0';
            value_text++;

            while ((*value_text == ' ') ||
                   (*value_text == '\t'))
            {
                value_text++;
            }

            value_ul = strtoul(
                value_text,
                &value_end,
                10);

            while ((*value_end == ' ') ||
                   (*value_end == '\t'))
            {
                value_end++;
            }

            if ((*value_text == '\0') ||
                (value_end == value_text) ||
                (*value_end != '\0') ||
                (value_ul > 0xFFFFFFFFUL))
            {
                Protocol_SendError(
                    request_id,
                    PROTO_ERR_BAD_ARGUMENT,
                    "BAD_VALUE");
            }
            else
            {
                (void)TightenParams_SetOne(
                    request_id,
                    arg,
                    (uint32_t)value_ul);
            }
        }
    }
    else if (strcmp(cmd, "START") == 0)
    {
        MotorJob_HandleUartStart(request_id);
    }
    else if (strcmp(cmd, "STOP") == 0)
    {
        MotorJob_QueueStop(request_id);
        (void)Protocol_SendFormatted(msg, sizeof(msg),
            "%lu OK STOP QUEUED\r\n", (unsigned long)request_id);
    }
    else if (strcmp(cmd, "RESULT") == 0)
    {
        if (Tightening_IsBusy() != 0U)
        {
            Protocol_SendError(
                request_id,
                PROTO_ERR_BUSY,
                "BUSY");
        }
        else
        {
            tightening_result_request_id = request_id;
            tightening_result_request = 1U;

            (void)Protocol_SendFormatted(
                msg,
                sizeof(msg),
                "%lu OK RESULT QUEUED\r\n",
                (unsigned long)request_id);
        }
    }
    else
    {
        Protocol_SendError(
            request_id,
            PROTO_ERR_UNKNOWN_COMMAND,
            "UNKNOWN_COMMAND");
    }
}

