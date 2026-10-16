#include "can_status_tx.h"
#include "can_log_v1.h"
#include "can_wire_profile.h"
#if CAN_WIRE_FD_ENABLED
#include "can_fd_probe.h"
#endif
#if defined(CAN_RPC_READ_ONLY)
#include "pw_can_rpc.h"
#endif

#if defined(CAN_SHADOW_DIAG)
#include "can_shadow_diag.h"
#endif
#if defined(CAN_CONTROL_REJECT_ONLY)
#include "can_control_v0.h"
#endif

#include "main.h"

#include <math.h>
#include <stdint.h>
#include <string.h>

/* PCLK1 170 MHz / (17 * (1 + 16 + 3)) = 500 kbit/s, 85% sample point. */
#define CAN_RECOVERY_INTERVAL_MS 5000U
#define CAN_FIFO_STALL_MS 2000U
#define CAN_MAX_RECOVERIES 3U
static FDCAN_HandleTypeDef status_can;
static uint16_t next_sequence;
static uint16_t next_motor_sequence;
static uint16_t next_electrical_sequence;
static uint8_t ready;
static CAN_StatusTx_Health health;
static uint32_t last_recovery_ms;
static uint32_t fifo_full_since_ms;
static uint8_t fifo_full_seen;
#if CAN_WIRE_FD_ENABLED
static uint8_t fd_pending_reply[CAN_FD_PROBE_BYTES];
static uint8_t fd_reply_pending;
static uint32_t fd_reply_created_ms;
static CAN_FdProbeHealth fd_health;
#endif
#if defined(CAN_SHADOW_DIAG)
static CanShadow_State shadow_state;
static CAN_ShadowHealth shadow_health;
static uint8_t shadow_pending_reply[8];
static uint8_t shadow_reply_pending;
static uint32_t shadow_reply_created_ms;
#endif
#if defined(CAN_CONTROL_REJECT_ONLY)
static CanControlV0_Session control_reject_session;
static CAN_ControlRejectHealth control_reject_health;
static uint8_t control_pending_reply[8];
static uint8_t control_reply_pending;
static uint32_t control_reply_created_ms;
#endif

static uint8_t start_controller(void);
#if defined(CAN_SHADOW_DIAG)
static void shadow_service(uint32_t now_ms);
#endif
#if defined(CAN_CONTROL_REJECT_ONLY)
static void control_reject_service(uint32_t now_ms);
#endif

static void stop_controller(void)
{
    if (ready != 0U) {
        (void)HAL_FDCAN_Stop(&status_can);
    }
    (void)HAL_FDCAN_DeInit(&status_can);
    ready = 0U;
    health.ready = 0U;
    fifo_full_seen = 0U;
#if CAN_WIRE_FD_ENABLED
    fd_reply_pending = 0U;
#endif
#if defined(CAN_RPC_READ_ONLY)
    PW_CanRpc_ResetLink(0U);
#endif
#if defined(CAN_SHADOW_DIAG)
    CanShadow_Reset(&shadow_state);
    shadow_reply_pending = 0U;
#endif
#if defined(CAN_CONTROL_REJECT_ONLY)
    CanControlV0_Reset(&control_reject_session, 0U);
    control_reply_pending = 0U;
#endif
}

static uint8_t enqueue_payload(uint32_t identifier, const uint8_t *data, uint32_t dlc)
{
    FDCAN_TxHeaderTypeDef header = {0};

    if (!CanWire_TxAllowed(identifier, CAN_WIRE_FD_ECHO_ONLY)) return 0U;
    if (ready == 0U) return 0U;
    if (HAL_FDCAN_GetTxFifoFreeLevel(&status_can) == 0U) {
        ++health.tx_fifo_full;
        return 0U;
    }

    header.Identifier = identifier;
    header.IdType = FDCAN_STANDARD_ID;
    header.TxFrameType = FDCAN_DATA_FRAME;
    header.DataLength = dlc;
    header.ErrorStateIndicator = FDCAN_ESI_ACTIVE;
    header.BitRateSwitch = CAN_WIRE_BRS_ENABLED ? FDCAN_BRS_ON : FDCAN_BRS_OFF;
    header.FDFormat = CAN_WIRE_FD_ENABLED ? FDCAN_FD_CAN : FDCAN_CLASSIC_CAN;
    header.TxEventFifoControl = FDCAN_STORE_TX_EVENTS;

    if (HAL_FDCAN_AddMessageToTxFifoQ(&status_can, &header, data) != HAL_OK) {
        ++health.tx_add_failures;
        return 0U;
    }
    ++health.tx_enqueued; /* Enqueued is not proof of ACK or on-wire delivery. */
    return 1U;
}

static uint8_t enqueue(uint32_t identifier, const uint8_t data[8])
{
    return enqueue_payload(identifier, data, FDCAN_DLC_BYTES_8);
}

static void drain_tx_events(void)
{
    FDCAN_TxEventFifoTypeDef event = {0};
    while ((status_can.Instance->TXEFS & FDCAN_TXEFS_EFFL) != 0U) {
        if (HAL_FDCAN_GetTxEvent(&status_can, &event) != HAL_OK) break;
        if (event.EventType == FDCAN_TX_EVENT || event.EventType == FDCAN_TX_IN_SPITE_OF_ABORT)
            ++health.tx_completed;
    }
    if ((status_can.Instance->TXEFS & FDCAN_TXEFS_TEFL) != 0U) {
        ++health.tx_event_lost;
        __HAL_FDCAN_CLEAR_FLAG(&status_can, FDCAN_FLAG_TX_EVT_FIFO_ELT_LOST);
    }
}

uint8_t CAN_StatusTx_TryLogFrame(uint32_t id, const uint8_t data[8])
{
    FDCAN_ProtocolStatusTypeDef protocol = {0};
    FDCAN_ErrorCountersTypeDef counters = {0};
    if (!ready || !data || (id != CAN_LOG_START_ID && id != CAN_LOG_DATA_ID &&
                            id != CAN_LOG_STATS_ID)) return 0U;
    drain_tx_events();
    if (HAL_FDCAN_GetProtocolStatus(&status_can, &protocol) != HAL_OK ||
        HAL_FDCAN_GetErrorCounters(&status_can, &counters) != HAL_OK ||
        protocol.BusOff || protocol.ErrorPassive || protocol.Warning ||
        counters.TxErrorCnt || counters.RxErrorCnt ||
        HAL_FDCAN_GetTxFifoFreeLevel(&status_can) < 2U) return 0U;
    return enqueue(id, data);
}

#if defined(CAN_RPC_READ_ONLY)
uint8_t CAN_StatusTx_TryRpcFrame(uint32_t id, const uint8_t data[8])
{
    FDCAN_ProtocolStatusTypeDef protocol = {0};
    FDCAN_ErrorCountersTypeDef counters = {0};
    if (id != CAN_RPC_REPLY_ID || data == NULL || !ready ||
        HAL_FDCAN_GetProtocolStatus(&status_can, &protocol) != HAL_OK ||
        HAL_FDCAN_GetErrorCounters(&status_can, &counters) != HAL_OK ||
        protocol.BusOff || protocol.ErrorPassive || protocol.Warning ||
        counters.TxErrorCnt || counters.RxErrorCnt ||
        HAL_FDCAN_GetTxFifoFreeLevel(&status_can) < 2U) return 0U;
    return enqueue(id, data);
}
#endif

#if defined(CAN_RPC_READ_ONLY) || CAN_WIRE_FD_ENABLED
static void read_only_receive_service(uint32_t now_ms)
{
    if (__HAL_FDCAN_GET_FLAG(&status_can, FDCAN_FLAG_RX_FIFO0_MESSAGE_LOST)) {
        __HAL_FDCAN_CLEAR_FLAG(&status_can, FDCAN_FLAG_RX_FIFO0_MESSAGE_LOST);
#if defined(CAN_RPC_READ_ONLY)
        PW_CanRpc_ResetLink(1U);
#endif
#if CAN_WIRE_FD_ENABLED
        ++fd_health.fifo_overruns;
        fd_reply_pending = 0U;
#endif
        /* Discard surviving frames too: loss may have spliced two packets. */
        for (unsigned i = 0U; i < 3U; ++i) {
            FDCAN_RxHeaderTypeDef header; uint8_t bytes[64];
            if (!HAL_FDCAN_GetRxFifoFillLevel(&status_can, FDCAN_RX_FIFO0)) break;
            if (HAL_FDCAN_GetRxMessage(&status_can, FDCAN_RX_FIFO0, &header, bytes) != HAL_OK) break;
        }
        return;
    }
    for (unsigned i = 0U; i < 3U; ++i) {
        FDCAN_RxHeaderTypeDef header; uint8_t bytes[64];
        if (!HAL_FDCAN_GetRxFifoFillLevel(&status_can, FDCAN_RX_FIFO0)) break;
        if (HAL_FDCAN_GetRxMessage(&status_can, FDCAN_RX_FIFO0, &header, bytes) != HAL_OK) {
#if defined(CAN_RPC_READ_ONLY)
            PW_CanRpc_ResetLink(1U);
#endif
            break;
        }
#if CAN_WIRE_FD_ENABLED
        if (header.Identifier == CAN_FD_PROBE_REQUEST_ID) {
            ++fd_health.received;
            if (header.IdType != FDCAN_STANDARD_ID || header.RxFrameType != FDCAN_DATA_FRAME ||
                header.FDFormat != FDCAN_FD_CAN ||
                header.ErrorStateIndicator != FDCAN_ESI_ACTIVE ||
                ((header.BitRateSwitch == FDCAN_BRS_ON) != (CAN_WIRE_BRS_ENABLED != 0)) ||
                !CanFdProbe_Validate(bytes, CanWire_DlcBytes(header.DataLength))) {
                ++fd_health.rejected;
            } else if (fd_reply_pending) {
                ++fd_health.dropped;
            } else {
                memcpy(fd_pending_reply, bytes, CAN_FD_PROBE_BYTES);
                fd_reply_pending = 1U;
                fd_reply_created_ms = now_ms;
            }
            continue;
        }
#endif
#if defined(CAN_RPC_READ_ONLY)
        /* Normalize only after checking the selected wire profile. The RPC
         * fragment ABI is still eight bytes; it is not a 64-byte optimization. */
        PW_CanRpc_Receive(header.Identifier, header.IdType != FDCAN_STANDARD_ID,
            header.RxFrameType != FDCAN_DATA_FRAME,
            !CanWire_ModeMatches(CAN_WIRE_FD_ENABLED, header.FDFormat == FDCAN_FD_CAN),
            CanWire_DlcBytes(header.DataLength), bytes, now_ms);
#endif
    }
#if CAN_WIRE_FD_ENABLED
    if (fd_reply_pending) {
        FDCAN_ProtocolStatusTypeDef protocol = {0};
        FDCAN_ErrorCountersTypeDef counters = {0};
        if ((uint32_t)(now_ms - fd_reply_created_ms) >= CAN_FD_PROBE_LIFETIME_MS) {
            ++fd_health.dropped;
            fd_reply_pending = 0U;
        } else if (HAL_FDCAN_GetProtocolStatus(&status_can, &protocol) == HAL_OK &&
                   HAL_FDCAN_GetErrorCounters(&status_can, &counters) == HAL_OK &&
                   !protocol.BusOff && !protocol.ErrorPassive && !protocol.Warning &&
                   !counters.TxErrorCnt && !counters.RxErrorCnt &&
                   HAL_FDCAN_GetTxFifoFreeLevel(&status_can) >= 2U &&
                   enqueue_payload(CAN_FD_PROBE_REPLY_ID, fd_pending_reply, FDCAN_DLC_BYTES_64)) {
            ++fd_health.echoes_enqueued;
            fd_reply_pending = 0U;
        }
    }
#endif
}
#endif

#if defined(CAN_SHADOW_DIAG)
static void shadow_service(uint32_t now_ms)
{
    FDCAN_RxHeaderTypeDef rx_header = {0};
    uint8_t rx_data[64] = {0};
    CanShadow_Request request;
    CanShadow_Decision decision;

    shadow_health.probe_timeouts += CanShadow_Tick(&shadow_state, now_ms);
    if (__HAL_FDCAN_GET_FLAG(&status_can, FDCAN_FLAG_RX_FIFO0_MESSAGE_LOST) != 0U) {
        ++shadow_health.fifo_overruns;
        __HAL_FDCAN_CLEAR_FLAG(&status_can, FDCAN_FLAG_RX_FIFO0_MESSAGE_LOST);
    }

    /* Reply at most once per 100 ms monitor tick. A pending reply is sent
       before new telemetry; no request can reach a motor-control function. */
    if (shadow_reply_pending != 0U) {
        if (enqueue(CAN_SHADOW_REPLY_ID, shadow_pending_reply) != 0U) {
            ++shadow_health.replies_queued;
            shadow_reply_pending = 0U;
        } else if ((uint32_t)(now_ms - shadow_reply_created_ms) >
                   CAN_SHADOW_WINDOW_MS) {
            ++shadow_health.replies_dropped;
            shadow_reply_pending = 0U;
        }
        return;
    }
    if (HAL_FDCAN_GetRxFifoFillLevel(&status_can, FDCAN_RX_FIFO0) == 0U)
        return;
    if (HAL_FDCAN_GetRxMessage(&status_can, FDCAN_RX_FIFO0,
                               &rx_header, rx_data) != HAL_OK) {
        ++shadow_health.invalid_frames;
        return;
    }
    ++shadow_health.received;
    if (CanShadow_DecodeRequest(rx_header.Identifier,
            (uint8_t)(rx_header.IdType != FDCAN_STANDARD_ID),
            (uint8_t)(rx_header.RxFrameType != FDCAN_DATA_FRAME),
            !CanWire_ModeMatches(CAN_WIRE_FD_ENABLED, rx_header.FDFormat == FDCAN_FD_CAN),
            CanWire_DlcBytes(rx_header.DataLength), rx_data, &request) == 0U) {
        ++shadow_health.invalid_frames;
        return;
    }

    decision = CanShadow_Evaluate(&shadow_state, &request, now_ms);
    if (decision == CAN_SHADOW_STOP_OBSERVED_NO_ACTION)
        ++shadow_health.stop_tests;
    if (decision == CAN_SHADOW_REJECT_RANGE)
        ++shadow_health.range_rejects;
    if (CanShadow_EncodeReply(&request, decision, shadow_pending_reply) == 0U) {
        ++shadow_health.invalid_frames;
        return;
    }
    shadow_reply_created_ms = now_ms;
    shadow_reply_pending = 1U;
}
#endif

#if defined(CAN_CONTROL_REJECT_ONLY)
static void control_reject_service(uint32_t now_ms)
{
    FDCAN_RxHeaderTypeDef rx_header = {0};
    uint8_t rx_data[64] = {0};
    CanControlV0_Request request;
    CanControlV0_Reply reply;

    if (__HAL_FDCAN_GET_FLAG(&status_can, FDCAN_FLAG_RX_FIFO1_MESSAGE_LOST) != 0U) {
        ++control_reject_health.fifo_overruns;
        __HAL_FDCAN_CLEAR_FLAG(&status_can, FDCAN_FLAG_RX_FIFO1_MESSAGE_LOST);
    }
    if (control_reply_pending != 0U) {
        if (enqueue(CAN_CONTROL_V0_REPLY_ID, control_pending_reply) != 0U) {
            ++control_reject_health.replies_queued;
            control_reply_pending = 0U;
        } else if ((uint32_t)(now_ms - control_reply_created_ms) > 500U) {
            ++control_reject_health.replies_dropped;
            control_reply_pending = 0U;
        }
        return;
    }
    if (HAL_FDCAN_GetRxFifoFillLevel(&status_can, FDCAN_RX_FIFO1) == 0U)
        return;
    if (HAL_FDCAN_GetRxMessage(&status_can, FDCAN_RX_FIFO1,
                               &rx_header, rx_data) != HAL_OK) {
        ++control_reject_health.invalid_frames;
        return;
    }
    ++control_reject_health.received;
    if (CanControlV0_ParseRequest(rx_header.Identifier,
            (uint8_t)(rx_header.IdType != FDCAN_STANDARD_ID),
            (uint8_t)(rx_header.RxFrameType != FDCAN_DATA_FRAME),
            !CanWire_ModeMatches(CAN_WIRE_FD_ENABLED, rx_header.FDFormat == FDCAN_FD_CAN),
            CanWire_DlcBytes(rx_header.DataLength), rx_data, &request) == 0U) {
        ++control_reject_health.invalid_frames;
        return;
    }

    /* No safety inputs or actuator functions are reachable from this path. */
    reply.opcode = request.opcode;
    reply.sequence = request.sequence;
    reply.decision = (uint8_t)CanControlV0_EvaluateDisabled(
        &control_reject_session, &request);
    reply.motor_mode = 0U;
    /* Echo the request token even for a rejection, so the host can reject
       unrelated/stale replies with the same 16-bit sequence. This does not
       grant a session or enable execution. */
    reply.session_token = request.session_token;
    if (CanControlV0_EncodeReply(&reply, control_pending_reply) == 0U) {
        ++control_reject_health.invalid_frames;
        return;
    }
    ++control_reject_health.rejected;
    control_reply_created_ms = now_ms;
    control_reply_pending = 1U;
}
#endif

void HAL_FDCAN_MspInit(FDCAN_HandleTypeDef *hfdcan)
{
    GPIO_InitTypeDef gpio = {0};
    if (hfdcan->Instance != FDCAN1) return;

    __HAL_RCC_GPIOB_CLK_ENABLE();
    __HAL_RCC_FDCAN_CLK_ENABLE();
    gpio.Pin = GPIO_PIN_8 | GPIO_PIN_9;
    gpio.Mode = GPIO_MODE_AF_PP;
    gpio.Pull = GPIO_NOPULL;
    gpio.Speed = GPIO_SPEED_FREQ_VERY_HIGH;
    gpio.Alternate = GPIO_AF9_FDCAN1;
    HAL_GPIO_Init(GPIOB, &gpio);
}

void HAL_FDCAN_MspDeInit(FDCAN_HandleTypeDef *hfdcan)
{
    if (hfdcan->Instance != FDCAN1) return;
    HAL_GPIO_DeInit(GPIOB, GPIO_PIN_8 | GPIO_PIN_9);
    __HAL_RCC_FDCAN_CLK_DISABLE();
}

uint8_t CAN_StatusTx_Init(void)
{
    ready = 0U;
    memset(&health, 0, sizeof(health));
#if CAN_WIRE_FD_ENABLED
    memset(&fd_health, 0, sizeof(fd_health));
    fd_reply_pending = 0U;
#endif
#if defined(CAN_SHADOW_DIAG)
    memset(&shadow_health, 0, sizeof(shadow_health));
    CanShadow_Reset(&shadow_state);
    shadow_reply_pending = 0U;
#endif
#if defined(CAN_CONTROL_REJECT_ONLY)
    memset(&control_reject_health, 0, sizeof(control_reject_health));
    CanControlV0_Reset(&control_reject_session, 0U);
    control_reply_pending = 0U;
#endif
    last_recovery_ms = HAL_GetTick();
    fifo_full_seen = 0U;
    next_sequence = 0U;
    next_motor_sequence = 0U;
    next_electrical_sequence = 0U;
    return start_controller();
}

static uint8_t start_controller(void)
{
    RCC_PeriphCLKInitTypeDef clock = {0};
#if CAN_WIRE_FD_ENABLED
    FDCAN_FilterTypeDef fd_filter = {0};
#endif
#if defined(CAN_RPC_READ_ONLY)
    FDCAN_FilterTypeDef rpc_filter = {0};
#endif
#if defined(CAN_SHADOW_DIAG)
    FDCAN_FilterTypeDef shadow_filter = {0};
#endif
#if defined(CAN_CONTROL_REJECT_ONLY)
    FDCAN_FilterTypeDef control_filter = {0};
#endif
    uint8_t clock_ready = 0U;
    ++health.init_attempts;
    status_can.Instance = FDCAN1;

    clock.PeriphClockSelection = RCC_PERIPHCLK_FDCAN;
    clock.FdcanClockSelection = RCC_FDCANCLKSOURCE_PCLK1;
    if (HAL_RCCEx_PeriphCLKConfig(&clock) != HAL_OK) goto fail;
    clock_ready = 1U;
#if CAN_WIRE_FD_ENABLED
    if (HAL_RCC_GetPCLK1Freq() != CAN_WIRE_CLOCK_HZ) goto fail;
#endif

    status_can.Init.ClockDivider = FDCAN_CLOCK_DIV1;
    status_can.Init.FrameFormat = CAN_WIRE_FD_ENABLED ?
        (CAN_WIRE_BRS_ENABLED ? FDCAN_FRAME_FD_BRS : FDCAN_FRAME_FD_NO_BRS) : FDCAN_FRAME_CLASSIC;
    status_can.Init.Mode = FDCAN_MODE_NORMAL;
    status_can.Init.AutoRetransmission = DISABLE;
    status_can.Init.TransmitPause = DISABLE;
    status_can.Init.ProtocolException = ENABLE;
    status_can.Init.NominalPrescaler = CAN_WIRE_NOMINAL_PRESCALER;
    status_can.Init.NominalSyncJumpWidth = 2U;
    status_can.Init.NominalTimeSeg1 = CAN_WIRE_NOMINAL_SEG1;
    status_can.Init.NominalTimeSeg2 = CAN_WIRE_NOMINAL_SEG2;
    status_can.Init.DataPrescaler = CAN_WIRE_FD_ENABLED ? CAN_WIRE_DATA_PRESCALER : 1U;
    status_can.Init.DataSyncJumpWidth = CAN_WIRE_FD_ENABLED ? 4U : 1U;
    status_can.Init.DataTimeSeg1 = CAN_WIRE_FD_ENABLED ? CAN_WIRE_DATA_SEG1 : 1U;
    status_can.Init.DataTimeSeg2 = CAN_WIRE_FD_ENABLED ? CAN_WIRE_DATA_SEG2 : 1U;
    status_can.Init.StdFiltersNbr = 0U;
#if defined(CAN_RPC_READ_ONLY)
    ++status_can.Init.StdFiltersNbr;
#endif
#if defined(CAN_SHADOW_DIAG)
    ++status_can.Init.StdFiltersNbr;
#endif
#if defined(CAN_CONTROL_REJECT_ONLY)
    ++status_can.Init.StdFiltersNbr;
#endif
#if CAN_WIRE_FD_ENABLED
    ++status_can.Init.StdFiltersNbr;
#endif
    status_can.Init.ExtFiltersNbr = 0U;
    status_can.Init.TxFifoQueueMode = FDCAN_TX_FIFO_OPERATION;

    if (HAL_FDCAN_Init(&status_can) != HAL_OK) goto fail;
#if CAN_WIRE_BRS_ENABLED
    if (HAL_FDCAN_ConfigTxDelayCompensation(&status_can, CAN_WIRE_TDC_OFFSET, 0U) != HAL_OK ||
        HAL_FDCAN_EnableTxDelayCompensation(&status_can) != HAL_OK) goto fail;
#endif

#if defined(CAN_RPC_READ_ONLY)
    rpc_filter.IdType = FDCAN_STANDARD_ID;
    rpc_filter.FilterIndex = 0U;
    rpc_filter.FilterType = FDCAN_FILTER_MASK;
    rpc_filter.FilterConfig = FDCAN_FILTER_TO_RXFIFO0;
    rpc_filter.FilterID1 = CAN_RPC_REQUEST_ID;
    rpc_filter.FilterID2 = 0x7FFU;
    if (HAL_FDCAN_ConfigFilter(&status_can, &rpc_filter) != HAL_OK) goto fail;
#endif

#if defined(CAN_SHADOW_DIAG)
    shadow_filter.IdType = FDCAN_STANDARD_ID;
    shadow_filter.FilterIndex = 0U;
    shadow_filter.FilterType = FDCAN_FILTER_MASK;
    shadow_filter.FilterConfig = FDCAN_FILTER_TO_RXFIFO0;
    shadow_filter.FilterID1 = CAN_SHADOW_REQUEST_ID;
    shadow_filter.FilterID2 = 0x7FFU;
    if (HAL_FDCAN_ConfigFilter(&status_can, &shadow_filter) != HAL_OK)
        goto fail;
#endif
#if defined(CAN_CONTROL_REJECT_ONLY)
    control_filter.IdType = FDCAN_STANDARD_ID;
#if defined(CAN_SHADOW_DIAG) || defined(CAN_RPC_READ_ONLY)
    control_filter.FilterIndex = 1U;
#else
    control_filter.FilterIndex = 0U;
#endif
    control_filter.FilterType = FDCAN_FILTER_MASK;
    control_filter.FilterConfig = FDCAN_FILTER_TO_RXFIFO1;
    control_filter.FilterID1 = CAN_CONTROL_V0_REQUEST_ID;
    control_filter.FilterID2 = 0x7FFU;
    if (HAL_FDCAN_ConfigFilter(&status_can, &control_filter) != HAL_OK)
        goto fail;
#endif
    /* The last filter is reserved for the fixed-size, read-only FD echo. */
#if CAN_WIRE_FD_ENABLED
    fd_filter.IdType = FDCAN_STANDARD_ID;
    fd_filter.FilterIndex = status_can.Init.StdFiltersNbr - 1U;
    fd_filter.FilterType = FDCAN_FILTER_MASK;
    fd_filter.FilterConfig = FDCAN_FILTER_TO_RXFIFO0;
    fd_filter.FilterID1 = CAN_FD_PROBE_REQUEST_ID;
    fd_filter.FilterID2 = 0x7FFU;
    if (HAL_FDCAN_ConfigFilter(&status_can, &fd_filter) != HAL_OK) goto fail;
#endif
    /* All other data frames and all remote frames remain rejected. */
    if (HAL_FDCAN_ConfigGlobalFilter(&status_can, FDCAN_REJECT, FDCAN_REJECT,
                                     FDCAN_REJECT_REMOTE,
                                     FDCAN_REJECT_REMOTE) != HAL_OK)
    {
        goto fail;
    }
    if (HAL_FDCAN_Start(&status_can) != HAL_OK)
    {
        goto fail;
    }
    ready = 1U;
    health.ready = 1U;
    return 1U;

fail:
    ++health.init_failures;
    if (clock_ready != 0U) (void)HAL_FDCAN_DeInit(&status_can);
    ready = 0U;
    health.ready = 0U;
    return 0U;
}

void CAN_StatusTx_Service(uint32_t now_ms)
{
    FDCAN_ProtocolStatusTypeDef protocol = {0};
    FDCAN_ErrorCountersTypeDef counters = {0};
    FDCAN_TxEventFifoTypeDef tx_event = {0};
    uint32_t free_level;
    uint8_t fault = 0U;

    if (ready != 0U) {
        /* A Tx event is produced after a successful transmission, unlike
           AddMessageToTxFifoQ(), which only proves local queue acceptance. */
        while ((status_can.Instance->TXEFS & FDCAN_TXEFS_EFFL) != 0U) {
            if (HAL_FDCAN_GetTxEvent(&status_can, &tx_event) != HAL_OK) break;
            /* Both HAL event variants mean the frame was transmitted.  On
               this board, the observed events use IN_SPITE_OF_ABORT even
               though the application did not request cancellation. */
            if ((tx_event.EventType == FDCAN_TX_EVENT) ||
                (tx_event.EventType == FDCAN_TX_IN_SPITE_OF_ABORT)) {
                ++health.tx_completed;
            }
        }
        if ((status_can.Instance->TXEFS & FDCAN_TXEFS_TEFL) != 0U) {
            ++health.tx_event_lost;
            __HAL_FDCAN_CLEAR_FLAG(&status_can, FDCAN_FLAG_TX_EVT_FIFO_ELT_LOST);
        }
        (void)HAL_FDCAN_GetProtocolStatus(&status_can, &protocol);
        (void)HAL_FDCAN_GetErrorCounters(&status_can, &counters);
        health.last_error_code = protocol.LastErrorCode;
        health.tx_error_count = counters.TxErrorCnt;
        health.rx_error_count = counters.RxErrorCnt;
        free_level = HAL_FDCAN_GetTxFifoFreeLevel(&status_can);
        health.fifo_free = free_level;
        if (protocol.BusOff != 0U) {
            ++health.bus_off_events;
            fault = 1U;
        } else if (free_level == 0U) {
            if (fifo_full_seen == 0U) {
                fifo_full_seen = 1U;
                fifo_full_since_ms = now_ms;
            } else if ((uint32_t)(now_ms - fifo_full_since_ms) >= CAN_FIFO_STALL_MS) {
                ++health.fifo_stalls;
                fault = 1U;
            }
        } else {
            fifo_full_seen = 0U;
        }
        if (fault == 0U) {
#if defined(CAN_RPC_READ_ONLY) || CAN_WIRE_FD_ENABLED
            read_only_receive_service(now_ms);
#endif
#if defined(CAN_SHADOW_DIAG)
            shadow_service(now_ms);
#endif
#if defined(CAN_CONTROL_REJECT_ONLY)
            control_reject_service(now_ms);
#endif
            return;
        }
        stop_controller();
        last_recovery_ms = now_ms;
    }

    if (health.recovery_exhausted != 0U) return;
    if ((uint32_t)(now_ms - last_recovery_ms) < CAN_RECOVERY_INTERVAL_MS) return;
    if (health.recoveries >= CAN_MAX_RECOVERIES) {
        health.recovery_exhausted = 1U;
        return;
    }
    ++health.recoveries;
    last_recovery_ms = now_ms;
    /* A long recovery gap makes old HMI samples stale; restart the group
       sequence together so all three telemetry IDs can be paired again. */
    next_sequence = 0U;
    next_motor_sequence = 0U;
    next_electrical_sequence = 0U;
    (void)start_controller();
}

void CAN_StatusTx_GetHealth(CAN_StatusTx_Health *out)
{
    if (out != NULL) *out = health;
}

#if CAN_WIRE_FD_ENABLED
void CAN_StatusTx_GetFdProbeHealth(CAN_FdProbeHealth *out)
{
    if (out != NULL) *out = fd_health;
}
#endif

#if defined(SAFETY_LOCKED_BOOT)
uint8_t CAN_StatusTx_TrySafetyFrame(uint32_t id, const uint8_t data[8])
{
    if (data == NULL || (id != 0x184U && id != 0x185U && id != 0x186U)) return 0U;
    return enqueue(id, data);
}
#endif

#if defined(CAN_SHADOW_DIAG)
void CAN_StatusTx_GetShadowHealth(CAN_ShadowHealth *out)
{
    if (out != NULL) *out = shadow_health;
}
#endif
#if defined(CAN_CONTROL_REJECT_ONLY)
void CAN_StatusTx_GetControlRejectHealth(CAN_ControlRejectHealth *out)
{
    if (out != NULL) *out = control_reject_health;
}
#endif

void CAN_StatusTx_Publish(uint8_t mode, uint8_t flags, uint16_t fault_code)
{
    uint8_t data[8];

    data[0] = 1U;
    data[1] = mode;
    data[2] = flags;
    data[3] = (uint8_t)fault_code;
    data[4] = (uint8_t)(fault_code >> 8);
    data[5] = (uint8_t)next_sequence;
    data[6] = (uint8_t)(next_sequence >> 8);
    data[7] = 0U;

    if (enqueue(CAN_STATUS_V1_ID, data) != 0U)
    {
        ++next_sequence;
    }
}

void CAN_StatusTx_PublishMotor(float angle_deg, float iq_A,
                               uint8_t angle_valid, uint8_t current_valid)
{
    uint8_t data[8];
    int32_t angle_mdeg = INT32_MIN;
    int16_t iq_mA = INT16_MIN;

    if ((angle_valid != 0U) && isfinite(angle_deg) &&
        (angle_deg > -2000000.0f) && (angle_deg < 2000000.0f))
        angle_mdeg = (int32_t)(angle_deg * 1000.0f);
    if ((current_valid != 0U) && isfinite(iq_A) &&
        (iq_A > -32.0f) && (iq_A < 32.0f))
        iq_mA = (int16_t)(iq_A * 1000.0f);

    data[0] = (uint8_t)(uint32_t)angle_mdeg;
    data[1] = (uint8_t)((uint32_t)angle_mdeg >> 8);
    data[2] = (uint8_t)((uint32_t)angle_mdeg >> 16);
    data[3] = (uint8_t)((uint32_t)angle_mdeg >> 24);
    data[4] = (uint8_t)(uint16_t)iq_mA;
    data[5] = (uint8_t)((uint16_t)iq_mA >> 8);
    data[6] = (uint8_t)next_motor_sequence;
    data[7] = (uint8_t)(next_motor_sequence >> 8);

    if (enqueue(CAN_MOTOR_V1_ID, data) != 0U) ++next_motor_sequence;
}

void CAN_StatusTx_PublishElectrical(uint32_t vbus_mv, float speed_rpm,
                                    uint8_t vbus_valid, uint8_t speed_valid)
{
    uint8_t data[8];
    uint8_t valid = 0U;
    int16_t speed_deci_rpm = 0;

    if ((vbus_valid != 0U) && (vbus_mv <= UINT16_MAX))
        valid |= 0x01U;
    else
        vbus_mv = 0U;
    if ((speed_valid != 0U) && isfinite(speed_rpm) &&
        (speed_rpm > -3276.0f) && (speed_rpm < 3276.0f))
    {
        speed_deci_rpm = (int16_t)(speed_rpm * 10.0f);
        valid |= 0x02U;
    }

    data[0] = (uint8_t)vbus_mv;
    data[1] = (uint8_t)(vbus_mv >> 8);
    data[2] = (uint8_t)(uint16_t)speed_deci_rpm;
    data[3] = (uint8_t)((uint16_t)speed_deci_rpm >> 8);
    data[4] = (uint8_t)next_electrical_sequence;
    data[5] = (uint8_t)(next_electrical_sequence >> 8);
    data[6] = valid;
    data[7] = 1U;

    if (enqueue(CAN_ELECTRICAL_V1_ID, data) != 0U) ++next_electrical_sequence;
}
