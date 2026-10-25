/* App A protocol/uart_transport.inc: private binding, included once by main.c.
 * Keep the declared include order and original control/IRQ ownership. */
/* Private user code ---------------------------------------------------------*/
/* USER CODE BEGIN 0 */
/*
 * StartupTask runs at priority 5 while UART TX service runs lower.
 * Do not enter the async enqueue path until StartupTask has completed and
 * deleted itself; otherwise the first runtime write can deadlock/starve the
 * TX service before it ever gets CPU time.
 */
static volatile uint8_t g_uart_async_runtime_enable = 0U;
static uint8_t g_safe_comm_boot = 0U;

/* NUCLEO-G474RE B1 USER is on PC13 with the board's default solder bridges.
 * This opt-in is sampled once at boot; no remote packet can change it. */
static uint8_t SafeCommBootRequested(void)
{
    GPIO_InitTypeDef gpio = {0};

    gpio.Pin = GPIO_PIN_13;
    gpio.Mode = GPIO_MODE_INPUT;
    gpio.Pull = GPIO_PULLDOWN;
    HAL_GPIO_Init(GPIOC, &gpio);

    if (HAL_GPIO_ReadPin(GPIOC, GPIO_PIN_13) != GPIO_PIN_SET)
    {
        return 0U;
    }
    HAL_Delay(30U);
    return (HAL_GPIO_ReadPin(GPIOC, GPIO_PIN_13) == GPIO_PIN_SET) ? 1U : 0U;
}

static void UART_SendString(const char *str)
{
    size_t len;

    if (str == NULL)
    {
        return;
    }

    len = strlen(str);

    /*
     * Before the scheduler/async backend exists, keep the proven blocking
     * path for the two boot messages.
     *
     * Once StartupTask initializes UART_Async, all normal application logging
     * becomes enqueue-only and no longer waits for the physical UART.
     */
    if ((g_rtos_started != 0U) &&
        (g_uart_async_runtime_enable != 0U))
    {
        /* A faulted DMA backend must not fall back to competing blocking TX. */
        (void)UART_Async_Write((const uint8_t *)str, len);
        return;
    }

    HAL_UART_Transmit(&hlpuart1,
                      (uint8_t *)str,
                      (uint16_t)len,
                      HAL_MAX_DELAY);
}

#define UART_PROTOCOL_TX_TIMEOUT_MS  250U
/* Private literal-only path. All callers below pass compile-time strings;
 * arbitrary/reusable caller buffers still use the copying compatibility API. */
static void UART_SendLiteral(const char *literal)
{
    if ((g_rtos_started != 0U) && (g_uart_async_runtime_enable != 0U)) {
        (void)UART_Async_WriteStatic((const uint8_t *)literal, strlen(literal));
        return;
    }
    UART_SendString(literal); /* preserve early boot's synchronous lifetime */
}

/* Generate directly into final DMA storage at runtime. The existing caller
 * array is only a pre-async boot fallback; never copied into TX at runtime. */
static void UART_SendFormatted(char *boot_buffer, size_t capacity, const char *format, ...)
{
    va_list args;
    va_start(args, format);
    if ((g_rtos_started != 0U) && (g_uart_async_runtime_enable != 0U)) {
        (void)UART_Async_VPrintf(capacity, 0U, format, args);
    } else {
        (void)vsnprintf(boot_buffer, capacity, format, args);
        UART_SendString(boot_buffer);
    }
    va_end(args);
}

/*
 * Reliable path for protocol/router traffic.
 *
 * Runtime logs remain best-effort and nonblocking through UART_SendString().
 * Commands, replies and Router frames get a bounded wait so they are not
 * silently lost when the fixed TX pool temporarily lacks a contiguous run.
 */
static uint8_t UART_SendReliableString(const char *str)
{
    size_t len;

    if (str == NULL)
    {
        return 0U;
    }

    len = strlen(str);

    if ((g_rtos_started != 0U) &&
        (g_uart_async_runtime_enable != 0U))
    {
        return (UART_Async_WriteReliable(
                    (const uint8_t *)str,
                    len,
                    UART_PROTOCOL_TX_TIMEOUT_MS) == len) ? 1U : 0U;
    }

    return (HAL_UART_Transmit(
                &hlpuart1,
                (uint8_t *)str,
                (uint16_t)len,
                HAL_MAX_DELAY) == HAL_OK) ? 1U : 0U;
}


/*
 * Router Stage 3: routed synchronous Protocol V2 reply context.
 *
 * Legacy UART commands keep the old raw UART response.
 * A ROUTER_PKT_PROTOCOL packet carries its source node into ProtocolTask.
 * While Protocol_HandleLine() executes, synchronous Protocol output is
 * wrapped back into ROUTER_PKT_PROTOCOL packets addressed to that source.
 */
static uint8_t protocol_reply_route_active = 0U;
static uint16_t protocol_reply_route_dst = 0U;
static volatile uint32_t protocol_reply_route_ok = 0U;
static volatile uint32_t protocol_reply_route_fail = 0U;
/* One COM5-initiated diagnostic request at a time. Never a motor command. */
static uint8_t protocol_esp_ping_uart_local = 0U;
static uint8_t protocol_esp_ping_pending = 0U;
static uint16_t protocol_esp_ping_request_id = 0U;
static TickType_t protocol_esp_ping_deadline = 0U;


static void Protocol_SetReplyRoute(uint16_t dst_node)
{
    if ((dst_node != 0U) &&
        (dst_node != ROUTER_BROADCAST_NODE) &&
        (dst_node != 1U))
    {
        protocol_reply_route_dst = dst_node;
        protocol_reply_route_active = 1U;
    }
    else
    {
        protocol_reply_route_dst = 0U;
        protocol_reply_route_active = 0U;
    }
}


static void Protocol_ClearReplyRoute(void)
{
    protocol_reply_route_active = 0U;
    protocol_reply_route_dst = 0U;
}


static uint8_t Protocol_SendString(const char *str)
{
    const char *p;
    uint8_t ok = 1U;

    if (str == NULL)
    {
        return 0U;
    }

    if (protocol_reply_route_active == 0U)
    {
        return UART_SendReliableString(str);
    }

    /*
     * Router UART framing is line based. Split CR/LF-separated Protocol
     * output into individual routed packets. Return failure if any packet
     * cannot be accepted by the Router, so critical IAP ACK paths can avoid
     * silently committing a half-visible protocol state.
     */
    p = str;

    while (*p != '\0')
    {
        const char *end = p;
        size_t len;
        char payload[ROUTER_MAX_PAYLOAD + 1U];

        while ((*end != '\0') &&
               (*end != '\r') &&
               (*end != '\n'))
        {
            end++;
        }

        len = (size_t)(end - p);

        if (len > 0U)
        {
            uint16_t seq = 0U;

            if (len > ROUTER_MAX_PAYLOAD)
            {
                protocol_reply_route_fail++;
                UART_SendLiteral("EVT ROUTER REPLY_TOO_LONG\r\n");
                return 0U;
            }

            memcpy(payload, p, len);
            payload[len] = '\0';

            if (Router_SendText(
                    protocol_reply_route_dst,
                    ROUTER_PKT_PROTOCOL,
                    payload,
                    &seq) != 0U)
            {
                protocol_reply_route_ok++;
            }
            else
            {
                protocol_reply_route_fail++;
                UART_SendLiteral("EVT ROUTER REPLY_NO_ROUTE\r\n");
                ok = 0U;
            }
        }

        while ((*end == '\r') || (*end == '\n'))
        {
            end++;
        }

        p = end;
    }

    return ok;
}

/* Known producers format into the final UART lease at runtime. A local array
 * is used only by synchronous boot/routed output; no borrowed stack TX. */
static uint8_t Protocol_SendFormatted(char *fallback, size_t capacity,
                                      const char *format, ...)
{
    uint8_t accepted;
    va_list args;
    va_start(args, format);
    accepted = ProtocolTx_VFormat(
        (protocol_reply_route_active == 0U && g_rtos_started != 0U &&
         g_uart_async_runtime_enable != 0U),
        UART_Async_VPrintf, Protocol_SendString, fallback, capacity,
        UART_PROTOCOL_TX_TIMEOUT_MS, format, args);
    va_end(args);
    return accepted;
}

static uint8_t UART_SendReliableFormatted(char *fallback, size_t capacity,
                                          const char *format, ...)
{
    uint8_t accepted;
    va_list args;
    va_start(args, format);
    accepted = ProtocolTx_VFormat(
        (g_rtos_started != 0U && g_uart_async_runtime_enable != 0U),
        UART_Async_VPrintf, UART_SendReliableString, fallback, capacity,
        UART_PROTOCOL_TX_TIMEOUT_MS, format, args);
    va_end(args);
    return accepted;
}

static uint8_t Modbus_Enqueue(const ModbusJob_t *job)
{
    ModbusJob_t queued;

    if ((job == NULL) || (modbus_request_queue == NULL))
    {
        return 0U;
    }
    queued = *job;
    queued.routed = protocol_reply_route_active;
    queued.reply_dst = protocol_reply_route_dst;
    if (xQueueSend(modbus_request_queue, &queued, 0U) != pdPASS)
    {
        modbus_queue_full++;
        return 0U;
    }
    modbus_submitted++;
    return 1U;
}

static void ModbusTask(void *argument)
{
    ModbusJob_t job;

    (void)argument;
    for (;;)
    {
        ModbusCompletion_t completion;

        if (xQueueReceive(modbus_request_queue, &job, portMAX_DELAY) != pdPASS)
        {
            continue;
        }
        memset(&completion, 0, sizeof(completion));
        completion.job = job;
        if ((motor_control_mode != MOTOR_MODE_IDLE) ||
            (Tightening_IsBusy() != 0U))
        {
            completion.busy = 1U;
        }
        else if (job.type == MODBUS_JOB_READ)
        {
            completion.result = ModbusProbe_ReadOne(
                job.baud, job.slave, job.function, job.address,
                job.even_parity, &completion.reply);
        }
        else
        {
            completion.result = ModbusProbe_SetRelay(
                job.relay, job.on, &completion.reply);
        }
        modbus_completed++;
        if ((completion.busy != 0U) ||
            (completion.result != MODBUS_PROBE_OK))
        {
            modbus_failed++;
        }
        if (completion.result == MODBUS_PROBE_TIMEOUT)
        {
            modbus_timeout++;
        }
        if (completion.result == MODBUS_PROBE_CRC_ERROR)
        {
            modbus_crc_error++;
        }
        /* Backpressure is bounded by the request queue; never lose a reply. */
        (void)xQueueSend(modbus_completion_queue, &completion, portMAX_DELAY);
    }
}

static void Modbus_ServiceCompletions(uint32_t budget)
{
    ModbusCompletion_t completion;
    uint32_t handled = 0U;

    while ((handled < budget) &&
           (xQueueReceive(modbus_completion_queue, &completion, 0U) == pdPASS))
    {
        const ModbusJob_t *job = &completion.job;
        const ModbusProbeReply_t *reply = &completion.reply;
        char line[192];

        if (job->routed != 0U)
        {
            Protocol_SetReplyRoute(job->reply_dst);
        }
        else
        {
            Protocol_ClearReplyRoute();
        }
        if (completion.busy != 0U)
        {
            (void)Protocol_SendFormatted(line, sizeof(line), "%lu ERR 101 MOTOR_NOT_IDLE\r\n",
                     (unsigned long)job->request_id);
        }
        else if (job->type == MODBUS_JOB_READ)
        {
            if (completion.result == MODBUS_PROBE_OK)
            {
                (void)Protocol_SendFormatted(line, sizeof(line),
                         "%lu OK MODBUS READ ID=%u FC=%u ADDR=%u VALUE=0x%04X DEC=%u RX=%u\r\n",
                         (unsigned long)job->request_id, job->slave,
                         job->function, job->address,
                         reply->value, reply->value, reply->received_bytes);
            }
            else if (completion.result == MODBUS_PROBE_EXCEPTION)
            {
                (void)Protocol_SendFormatted(line, sizeof(line),
                         "%lu OK MODBUS EXCEPTION ID=%u FC=%u CODE=%u RX=%u\r\n",
                         (unsigned long)job->request_id, job->slave,
                         job->function, reply->exception_code,
                         reply->received_bytes);
            }
            else
            {
                const char *name = completion.result == MODBUS_PROBE_TIMEOUT ? "TIMEOUT" :
                    completion.result == MODBUS_PROBE_CRC_ERROR ? "CRC" :
                    completion.result == MODBUS_PROBE_BAD_FRAME ? "BAD_FRAME" :
                    completion.result == MODBUS_PROBE_BAD_ARGUMENT ? "BAD_ARGUMENT" : "UART";
                (void)Protocol_SendFormatted(line, sizeof(line),
                         "%lu ERR MODBUS %s ID=%u FC=%u BAUD=%lu RX=%u UART=0x%lX\r\n",
                         (unsigned long)job->request_id, name, job->slave,
                         job->function, (unsigned long)job->baud,
                         reply->received_bytes, (unsigned long)reply->uart_error);
            }
        }
        else if (completion.result == MODBUS_PROBE_OK)
        {
            (void)Protocol_SendFormatted(line, sizeof(line),
                     "%lu OK MODBUS RELAY=%u STATE=%s ACK=1\r\n",
                     (unsigned long)job->request_id, job->relay,
                     job->on != 0U ? "ON" : "OFF");
        }
        else
        {
            const char *name = completion.result == MODBUS_PROBE_TIMEOUT ? "TIMEOUT" :
                completion.result == MODBUS_PROBE_CRC_ERROR ? "CRC" :
                completion.result == MODBUS_PROBE_BAD_FRAME ? "BAD_FRAME" :
                completion.result == MODBUS_PROBE_EXCEPTION ? "EXCEPTION" : "UART";
            (void)Protocol_SendFormatted(line, sizeof(line),
                     "%lu ERR MODBUS RELAY=%u %s CODE=%u RX=%u UART=0x%lX\r\n",
                     (unsigned long)job->request_id, job->relay, name,
                     reply->exception_code, reply->received_bytes,
                     (unsigned long)reply->uart_error);
        }
        (void)
        Protocol_ClearReplyRoute();
        handled++;
    }
}

/* C linkage bridge used by the C++ pw_rpc ChannelOutput. */
uint8_t PW_Rpc_ProtocolSend(const char *line)
{
    return Protocol_SendString(line);
}

#if defined(CAN_RPC_READ_ONLY)
/* Short RAM snapshots only. Never dispatch textual commands from CAN RPC. */
size_t PW_Rpc_ReadOnlySnapshot(uint32_t kind, uint8_t *out, size_t capacity)
{
    uint32_t words[RPC_READONLY_PARAMS_WORDS] = {RPC_READONLY_VERSION};
    size_t count = 0U;
    if (out == NULL) return 0U;
    if (kind == RPC_READONLY_SNAPSHOT_STATUS)
    {
        count = RPC_READONLY_STATUS_WORDS;
        taskENTER_CRITICAL();
        words[1] = HAL_GetTick();
        words[2] = (uint32_t)motor_control_mode;
        words[3] = (foc_enable != 0U ? 1U : 0U) |
                   (foc_fault != 0U ? 2U : 0U) |
                   (encoder_valid != 0U ? 4U : 0U);
        words[4] = foc_fault_reason;
        words[5] = analog_safe_latched;
        words[6] = fw_update.active;
        words[7] = 0U; /* CAN motion control is permanently rejected in this profile. */
        taskEXIT_CRITICAL();
    }
    else if (kind == RPC_READONLY_SNAPSHOT_PARAMS)
    {
        TightenParams_t snapshot;
        taskENTER_CRITICAL(); snapshot = recipe_state.params; taskEXIT_CRITICAL();
        size_t index = 1U;
#define RPC_PARAM_WORD(field, name, low, high, initial) words[index++] = snapshot.field;
        TIGHTEN_PARAM_FIELDS(RPC_PARAM_WORD)
#undef RPC_PARAM_WORD
        count = index;
    }
    else if (kind == RPC_READONLY_SNAPSHOT_DIAGNOSTICS)
    {
        PW_LogDiagnostics_t logs;
        CAN_StatusTx_Health can;
        PW_CanRpcDiagnostics rpc;
        PW_Log_GetDiagnostics(&logs);
        PW_CanRpc_GetCanSnapshot(&can);
        PW_CanRpc_GetDiagnostics(&rpc);
        count = RPC_READONLY_DIAG_WORDS;
        words[1] = logs.ready; words[2] = logs.enqueued;
        words[3] = logs.dropped_full; words[4] = logs.dropped_uart;
        words[5] = logs.dropped_pool; words[6] = can.ready;
        words[7] = can.bus_off_events; words[8] = can.recoveries;
        words[9] = rpc.fifo_overruns;
    }
    if (count == 0U || count * 4U > capacity) return 0U;
    for (size_t i = 0U; i < count; ++i)
        for (unsigned byte = 0U; byte < 4U; ++byte)
            out[i * 4U + byte] = (uint8_t)(words[i] >> (byte * 8U));
    return count * 4U;
}
#endif


/*
 * First real-time control task skeleton.
 *
 * This task runs at 1 kHz using vTaskDelayUntil(), which gives a fixed
 * absolute period suitable for later encoder/speed/position control.
 *
 * IMPORTANT FOR THIS STEP:
 * - The power stage remains disabled.
 * - The original 20 kHz current-loop FOC code is not moved yet.
 * - This task only proves stable 1 kHz periodic scheduling.
 */
#include "foc_fault_snapshot.inc"

