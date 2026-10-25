/* App A protocol/router_protocol_tasks.inc: private binding, included once by main.c.
 * Keep the declared include order and original control/IRQ ownership. */
static void Router_RxLine(const char *line, void *context)
{
    (void)context;
    if (Router_SubmitAsciiLine(ROUTER_PORT_UART1, line) == 0U)
        UART_SendLiteral("EVT ROUTER RX_DROP OR PARSE_ERROR\r\n");
}

static void Router_RxByte(uint8_t byte, void *context)
{
    if (UartLineParser_Byte((UartLineParser *)context, byte,
                            Router_RxLine, NULL) < 0)
        UART_SendLiteral("EVT ROUTER LINE_TOO_LONG\r\n");
}

static void Router_RxGap(void *context)
{
    UartLineParser_Gap((UartLineParser *)context);
}

static void RouterTask(void *argument)
{
#if defined(FOC_ISOLATED_CONCURRENCY)
    isolated_router_task = xTaskGetCurrentTaskHandle();
#endif
    TickType_t last_wake_time;
    UartLineParser parser;
    (void)argument;
    UartLineParser_Init(&parser);
    last_wake_time = xTaskGetTickCount();
    UART_SendLiteral(
        "\r\nRouterTask: DMA1_CH2 circular -> direct parser\r\n"
        "Legacy Protocol V2 lines remain locally compatible\r\n"
        "Loss/overflow: discard partial line to next delimiter\r\n"
        "Local node ID: 1\r\n\r\n");
    for (;;) {
        (void)UART_RxDma_Drain(Router_RxByte, Router_RxGap, &parser, 1024U);
        Router_Service(8U);
        Router_Maintenance();
        vTaskDelayUntil(&last_wake_time,
                       pdMS_TO_TICKS(UART_ROUTER_POLL_MS));
    }
}

/* Discovery-only full-APP bring-up. The motor, protocol and boot-health tasks
 * are deliberately absent, and UART1 command ingress is not initialized. */
static void SafeCommTask(void *argument)
{
    TickType_t last_report = xTaskGetTickCount();
    char msg[160];

    (void)argument;
    for (;;)
    {
        RouterStatus_t status;

        PowerStage_Disable();
        TIM1->BDTR &= ~TIM_BDTR_MOE;
        Router_Service(8U);
        Router_Maintenance();

        if ((xTaskGetTickCount() - last_report) >= pdMS_TO_TICKS(3000U))
        {
            Router_GetStatus(&status);
            UART_SendFormatted(msg, sizeof(msg),
                     "SAFE COMM ESP_NODE=%lu DISC_RX=%lu DISC_TX=%lu PARSE_ERR=%lu SD_ODR=%u MOE=%u\r\n",
                     (unsigned long)(Router_GetNodeCount() > 1U),
                     (unsigned long)status.discovery_rx,
                     (unsigned long)status.discovery_tx,
                     (unsigned long)status.parse_errors,
                     (unsigned int)((DRIVER_SD_GPIO_Port->ODR & DRIVER_SD_Pin) != 0U),
                     (unsigned int)((TIM1->BDTR & TIM_BDTR_MOE) != 0U));
            last_report = xTaskGetTickCount();
        }
        vTaskDelay(pdMS_TO_TICKS(5U));
    }
}


static void ProtocolTask(void *argument)
{
#if defined(FOC_ISOLATED_CONCURRENCY)
    isolated_protocol_task = xTaskGetCurrentTaskHandle();
#endif
    TickType_t last_wake_time;
    char line[ROUTER_MAX_PAYLOAD + 1U];

    (void)argument;

    last_wake_time = xTaskGetTickCount();

    UART_SendLiteral(
        "\r\n"
        "ProtocolTask Stage 4.3 started @ 5ms\r\n"
        "Input: Router LOCAL packet queue -> Protocol / EVT / EVT_ACK handlers\r\n"
        "Legacy UART request -> raw UART reply\r\n"
        "Routed PROTOCOL request -> routed synchronous reply\r\n"
        "Stage 4.3: async EVT uses EID + ACK + 500ms bounded retry\r\n"
        "Protocol V2 + IAP unchanged: <REQ_ID> <COMMAND>\r\n"
        "Router commands: STATUS / NODES / ROUTES / DISCOVER / CONFIG / CLEAR / SEND\r\n"
        "Device is IDLE until START is received\r\n\r\n");

    for (;;)
    {
        uint32_t processed = 0U;
        RouterPacket_t packet;

        /*
         * Stage 4.3 keeps all application-event transport/retry work in
         * ProtocolTask. TighteningTask only enqueues immutable event records.
         */
        Protocol_AsyncEventService(4U);
#if defined(UART_FIRMWARE_TRANSFER)
        PW_UartFirmwareTransfer_Service();
#endif
        PW_LogRouter_Service(4U);
#if defined(CAN_RPC_READ_ONLY)
        PW_CanRpc_ProtocolService();
#endif
#if !defined(ZERO_RETEST_BOOT)
        Modbus_ServiceCompletions(4U);
#endif
#if defined(ROUTER_READ_ONLY_TRANSFER)
        PW_RouterTransfer_Tick(HAL_GetTick());
#endif
        Protocol_EspPingService();

        while ((processed < 8U) &&
               (Router_LocalReadPacket(&packet) != 0U))
        {
            size_t len = packet.length;

            if (len > ROUTER_MAX_PAYLOAD)
            {
                len = ROUTER_MAX_PAYLOAD;
            }

            memcpy(line, packet.payload, len);
            line[len] = '\0';

#if defined(ROUTER_READ_ONLY_TRANSFER)
            if (packet.type == RN_TRANSFER_TYPE)
            {
                (void)PW_RouterTransfer_Process(&packet, HAL_GetTick());
                processed++;
                continue;
            }
#endif
#if defined(ROUTER_READ_ONLY_RPC)
            /* Dedicated typed endpoint: never send RPC bytes to the console.
             * ProtocolTask is the sole owner of synchronous unary RPC calls. */
            if (packet.type == RN_RPC_TYPE)
            {
                (void)PW_RouterRpc_Process(&packet, HAL_GetTick());
                processed++;
                continue;
            }
#endif
            if (packet.ingress_port == ROUTER_PORT_ESP32)
            {
                /* The ESP UART can deliver only a matched diagnostic PONG.
                 * Never pass ESP payloads into Protocol_HandleLine(). */
                Protocol_ClearReplyRoute();
                Protocol_EspPingHandlePacket(&packet);
            }
            else if (packet.type == PROTOCOL_ROUTER_TYPE_EVENT)
            {
                /* Reliable async event plane: deliver once, ACK every copy. */
                Protocol_ClearReplyRoute();
                Protocol_ReliableEventHandleEventPacket(&packet);
            }
            else if (packet.type == PROTOCOL_ROUTER_TYPE_EVENT_ACK)
            {
                /* ACK is router/application control traffic, not Protocol V2. */
                Protocol_ClearReplyRoute();
                Protocol_ReliableEventHandleAckPacket(&packet);
            }
            else if (packet.type == PW_LOG_ROUTER_PACKET_TYPE)
            {
                Protocol_ClearReplyRoute();
                PW_LogRouter_HandleRemote(&packet);
            }
            else
            {
                /*
                 * src=0 is Stage1/2 legacy UART compatibility.
                 * A real routed Protocol request remembers its source node so
                 * synchronous Protocol V2 replies can take the reverse route.
                 */
                if ((packet.type == ROUTER_PKT_PROTOCOL) &&
                    (packet.src != 0U) &&
                    (packet.src != ROUTER_LOCAL_NODE_ID) &&
                    (packet.src != ROUTER_BROADCAST_NODE))
                {
                    Protocol_SetReplyRoute(packet.src);
                }
                else
                {
                    Protocol_ClearReplyRoute();
                }

                protocol_esp_ping_uart_local =
                    ((packet.src == 0U) &&
                     (packet.ingress_port == ROUTER_PORT_UART1)) ? 1U : 0U;
                Protocol_HandleLine(line);
                protocol_esp_ping_uart_local = 0U;
                Protocol_ClearReplyRoute();
            }

            processed++;
        }

        /* Incoming ACK packets above can clear slots before this retry pass. */
        Protocol_ReliableEventService(4U);
#if !defined(ZERO_RETEST_BOOT)
        Modbus_ServiceCompletions(4U);
#endif

        vTaskDelayUntil(
            &last_wake_time,
            pdMS_TO_TICKS(5U));
    }
}


