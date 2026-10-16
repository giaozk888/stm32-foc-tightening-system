#include <stdint.h>
#include <stdio.h>
#include <string.h>

#include "stm32g4xx_hal.h"

/* 170 MHz / (17 * 20) or HSI16 / (2 * 16) = 500 kbit/s. */
static UART_HandleTypeDef console_uart;
static FDCAN_HandleTypeDef can1;
/* SRAM-only breadcrumbs for debugger inspection when the UART is unavailable. */
volatile uint32_t diag_phase;
volatile uint32_t diag_detail;
volatile uint32_t diag_sequence;

static void power_stage_off(void)
{
    GPIO_InitTypeDef pin = {0};
    __HAL_RCC_GPIOC_CLK_ENABLE();
    GPIOC->BSRR = GPIO_BSRR_BR6;
    pin.Pin = GPIO_PIN_6;
    pin.Mode = GPIO_MODE_OUTPUT_PP;
    pin.Pull = GPIO_NOPULL;
    pin.Speed = GPIO_SPEED_FREQ_LOW;
    HAL_GPIO_Init(GPIOC, &pin);
    HAL_GPIO_WritePin(GPIOC, GPIO_PIN_6, GPIO_PIN_RESET);
}

static void console_write(const char *message)
{
    (void)HAL_UART_Transmit(&console_uart, (const uint8_t *)message,
                            (uint16_t)strlen(message), 100U);
}

#ifndef CAN_RX_ONLY
/* A debugger-launched SRAM image may inherit a pending, unserviced SysTick.
 * COUNTFLAG still advances in hardware, so this diagnostic does not depend
 * on HAL_IncTick or any interrupt to bound its transmit cadence. */
static void tx_probe_wait_ms(uint32_t ms)
{
    for (uint32_t tick = 0U; tick < ms; ++tick) {
        uint32_t guard = 0U;
        while ((SysTick->CTRL & SysTick_CTRL_COUNTFLAG_Msk) == 0U) {
            if (++guard >= 1000000U) return;
        }
    }
}
#endif

void HAL_UART_MspInit(UART_HandleTypeDef *uart)
{
    GPIO_InitTypeDef pin = {0};
    if (uart->Instance != LPUART1) {
        return;
    }
    __HAL_RCC_GPIOA_CLK_ENABLE();
    __HAL_RCC_LPUART1_CLK_ENABLE();
    /* A debugger RAM launch does not reset an already-enabled UART. */
    __HAL_RCC_LPUART1_FORCE_RESET();
    __HAL_RCC_LPUART1_RELEASE_RESET();
    pin.Pin = GPIO_PIN_2 | GPIO_PIN_3;
    pin.Mode = GPIO_MODE_AF_PP;
    pin.Pull = GPIO_NOPULL;
    pin.Speed = GPIO_SPEED_FREQ_LOW;
    pin.Alternate = GPIO_AF12_LPUART1;
    HAL_GPIO_Init(GPIOA, &pin);
}

void HAL_FDCAN_MspInit(FDCAN_HandleTypeDef *can)
{
    GPIO_InitTypeDef pin = {0};
    if (can->Instance != FDCAN1) {
        return;
    }
    __HAL_RCC_GPIOB_CLK_ENABLE();
    __HAL_RCC_FDCAN_CLK_ENABLE();
    /* Discard the previous probe's bus-off and message-RAM state. */
    __HAL_RCC_FDCAN_FORCE_RESET();
    __HAL_RCC_FDCAN_RELEASE_RESET();
    pin.Pin = GPIO_PIN_8 | GPIO_PIN_9;
    pin.Mode = GPIO_MODE_AF_PP;
    pin.Pull = GPIO_NOPULL;
    pin.Speed = GPIO_SPEED_FREQ_VERY_HIGH;
    pin.Alternate = GPIO_AF9_FDCAN1;
    HAL_GPIO_Init(GPIOB, &pin);
}

void SysTick_Handler(void)
{
    HAL_IncTick();
}

static void stop_forever(const char *reason)
{
    console_write(reason);
    for (;;) {
        power_stage_off();
        HAL_Delay(1000U);
    }
}

int main(void)
{
    RCC_PeriphCLKInitTypeDef clock = {0};
#ifndef CAN_RX_ONLY
    FDCAN_TxHeaderTypeDef tx = {0};
#ifdef CAN_STATUS_V1_PROBE
    /* Diagnostic marker: IDLE + fault, never a claim that the full APP booted. */
    uint8_t payload[8] = {1U, 0U, 0x02U, 0xFEU, 0xFFU, 0U, 0U, 0U};
#else
    uint8_t payload[8] = {'C', 'A', 'N', '2', 0U, 0U, 0U, 0U};
#endif
#endif
    char line[160];
#ifndef CAN_STATUS_V1_PROBE
    uint32_t rx_count = 0U;
#endif
    uint32_t pclk1;

    /* A RAM launch inherits the previous application's interrupt state. */
    __disable_irq();
    power_stage_off();
    SysTick->CTRL = 0U;
    for (uint32_t bank = 0U; bank < 4U; ++bank) {
        NVIC->ICER[bank] = 0xFFFFFFFFU;
        NVIC->ICPR[bank] = 0xFFFFFFFFU;
    }
    SCB->ICSR = SCB_ICSR_PENDSTCLR_Msk | SCB_ICSR_PENDSVCLR_Msk;
    SCB->VTOR = DIAG_VECTOR_BASE;
    /* RAM loading does not reset RCC. Synchronize HAL with the inherited clock. */
    SystemCoreClockUpdate();
    HAL_Init();
    power_stage_off();
    __enable_irq();
    diag_phase = 1U;

    console_uart.Instance = LPUART1;
    console_uart.Init.BaudRate = 115200U;
    console_uart.Init.WordLength = UART_WORDLENGTH_8B;
    console_uart.Init.StopBits = UART_STOPBITS_1;
    console_uart.Init.Parity = UART_PARITY_NONE;
    console_uart.Init.Mode = UART_MODE_TX_RX;
    console_uart.Init.HwFlowCtl = UART_HWCONTROL_NONE;
    console_uart.Init.OverSampling = UART_OVERSAMPLING_16;
    console_uart.Init.OneBitSampling = UART_ONE_BIT_SAMPLE_DISABLE;
    console_uart.Init.ClockPrescaler = UART_PRESCALER_DIV1;
    diag_detail = (uint32_t)HAL_UART_Init(&console_uart);
    diag_phase = 2U;
    if (diag_detail != HAL_OK) {
        stop_forever("CAN RAM DIAG: COM init failed; SD=0\r\n");
    }
#ifdef CAN_RX_ONLY
    console_write("CAN RAM RX ONLY: SD=0, PWM/FOC OFF, 30 seconds max\r\n");
#elif defined(CAN_STATUS_V1_PROBE)
    console_write("CAN RAM STATUS V1 ONLY: SD=0, PWM/FOC OFF, 50 frames max\r\n");
#else
    console_write("CAN RAM DIAG ONLY: SD=0, PWM/FOC OFF, 10 frames max\r\n");
#endif

    clock.PeriphClockSelection = RCC_PERIPHCLK_FDCAN;
    clock.FdcanClockSelection = RCC_FDCANCLKSOURCE_PCLK1;
    diag_detail = (uint32_t)HAL_RCCEx_PeriphCLKConfig(&clock);
    diag_phase = 3U;
    if (diag_detail != HAL_OK) {
        stop_forever("CAN RAM DIAG: CAN clock failed\r\n");
    }
    pclk1 = HAL_RCC_GetPCLK1Freq();
    (void)snprintf(line, sizeof(line), "CAN RAM DIAG: PCLK1=%lu\r\n",
                   (unsigned long)pclk1);
    console_write(line);
    if (pclk1 != 170000000U && pclk1 != 16000000U) {
        stop_forever("CAN RAM DIAG: unsupported PCLK1; CAN not started\r\n");
    }

    can1.Instance = FDCAN1;
    can1.Init.ClockDivider = FDCAN_CLOCK_DIV1;
    can1.Init.FrameFormat = FDCAN_FRAME_CLASSIC;
    can1.Init.Mode = FDCAN_MODE_NORMAL;
    can1.Init.AutoRetransmission = DISABLE;
    can1.Init.TransmitPause = DISABLE;
    can1.Init.ProtocolException = ENABLE;
    can1.Init.NominalPrescaler = (pclk1 == 170000000U) ? 17U : 2U;
    can1.Init.NominalSyncJumpWidth = 2U;
    can1.Init.NominalTimeSeg1 = (pclk1 == 170000000U) ? 16U : 13U;
    can1.Init.NominalTimeSeg2 = (pclk1 == 170000000U) ? 3U : 2U;
    can1.Init.DataPrescaler = 1U;
    can1.Init.DataSyncJumpWidth = 1U;
    can1.Init.DataTimeSeg1 = 1U;
    can1.Init.DataTimeSeg2 = 1U;
    can1.Init.StdFiltersNbr = 0U;
    can1.Init.ExtFiltersNbr = 0U;
    can1.Init.TxFifoQueueMode = FDCAN_TX_FIFO_OPERATION;
    diag_detail = (uint32_t)HAL_FDCAN_Init(&can1);
    diag_phase = 4U;
    if (diag_detail != HAL_OK ||
        (diag_detail = (uint32_t)HAL_FDCAN_ConfigGlobalFilter(
            &can1, FDCAN_ACCEPT_IN_RX_FIFO0, FDCAN_ACCEPT_IN_RX_FIFO0,
            FDCAN_REJECT_REMOTE, FDCAN_REJECT_REMOTE)) != HAL_OK) {
        stop_forever("CAN RAM DIAG: CAN init failed\r\n");
    }

#ifndef CAN_RX_ONLY
#ifdef CAN_STATUS_V1_PROBE
    tx.Identifier = 0x180U;
#else
    tx.Identifier = 0x701U;
#endif
    tx.IdType = FDCAN_STANDARD_ID;
    tx.TxFrameType = FDCAN_DATA_FRAME;
    tx.DataLength = FDCAN_DLC_BYTES_8;
    tx.ErrorStateIndicator = FDCAN_ESI_ACTIVE;
    tx.BitRateSwitch = FDCAN_BRS_OFF;
    tx.FDFormat = FDCAN_CLASSIC_CAN;
    tx.TxEventFifoControl = FDCAN_NO_TX_EVENTS;
#endif
    diag_detail = (uint32_t)HAL_FDCAN_Start(&can1);
    diag_phase = 5U;
    if (diag_detail != HAL_OK) {
        stop_forever("CAN RAM DIAG: CAN start failed\r\n");
    }
#ifdef CAN_RX_ONLY
    console_write("CAN RAM RX DIAG: PB8 RX, 500k, listening 30 seconds\r\n");
    for (uint32_t tick = 0U; tick < 300U; ++tick) {
        power_stage_off();
        while (HAL_FDCAN_GetRxFifoFillLevel(&can1, FDCAN_RX_FIFO0) != 0U) {
            FDCAN_RxHeaderTypeDef rx = {0};
            uint8_t rx_data[64] = {0};
            if (HAL_FDCAN_GetRxMessage(&can1, FDCAN_RX_FIFO0, &rx, rx_data) != HAL_OK) {
                break;
            }
            ++rx_count;
            (void)snprintf(line, sizeof(line),
                           "CAN RX id=%03lX dlc=%08lX data=%02X%02X%02X%02X count=%lu\r\n",
                           (unsigned long)rx.Identifier,
                           (unsigned long)rx.DataLength,
                           (unsigned)rx_data[0], (unsigned)rx_data[1],
                           (unsigned)rx_data[2], (unsigned)rx_data[3],
                           (unsigned long)rx_count);
            console_write(line);
        }
        HAL_Delay(100U);
    }
    (void)HAL_FDCAN_Stop(&can1);
    stop_forever("CAN RAM RX DIAG DONE: CAN stopped; SD=0\r\n");
#else
#ifdef CAN_STATUS_V1_PROBE
    console_write("CAN RAM STATUS V1: PB9 TX, 500k, ID 180, fault marker FFFE\r\n");
    for (uint32_t sequence = 0U; sequence < 50U; ++sequence) {
        FDCAN_ErrorCountersTypeDef errors = {0};
        FDCAN_ProtocolStatusTypeDef status = {0};
        HAL_StatusTypeDef send = HAL_BUSY;
        power_stage_off();
        payload[5] = (uint8_t)sequence;
        payload[6] = (uint8_t)(sequence >> 8);
        if (HAL_FDCAN_GetTxFifoFreeLevel(&can1) != 0U) {
            send = HAL_FDCAN_AddMessageToTxFifoQ(&can1, &tx, payload);
        }
        tx_probe_wait_ms(30U);
        (void)HAL_FDCAN_GetErrorCounters(&can1, &errors);
        (void)HAL_FDCAN_GetProtocolStatus(&can1, &status);
        if ((sequence % 10U) == 0U || send != HAL_OK || status.BusOff != 0U) {
            (void)snprintf(line, sizeof(line),
                           "CAN STATUS seq=%lu enqueue=%u TXBTO=%lX TEC=%lu BO=%lu SD=0\r\n",
                           (unsigned long)sequence, (unsigned)send,
                           (unsigned long)FDCAN1->TXBTO,
                           (unsigned long)errors.TxErrorCnt,
                           (unsigned long)status.BusOff);
            console_write(line);
        }
        if (status.BusOff != 0U) break;
        tx_probe_wait_ms(70U);
    }
    (void)HAL_FDCAN_Stop(&can1);
    stop_forever("CAN RAM STATUS V1 DONE: CAN stopped; SD=0\r\n");
#else
    console_write("CAN RAM DIAG: PB8 RX / PB9 TX, 500k, ID 701\r\n");
    for (uint32_t sequence = 0U; sequence < 10U; ++sequence) {
        FDCAN_ErrorCountersTypeDef errors = {0};
        FDCAN_ProtocolStatusTypeDef status = {0};
        HAL_StatusTypeDef send = HAL_BUSY;
        power_stage_off();
        payload[4] = (uint8_t)(sequence >> 24);
        payload[5] = (uint8_t)(sequence >> 16);
        payload[6] = (uint8_t)(sequence >> 8);
        payload[7] = (uint8_t)sequence;
        if (HAL_FDCAN_GetTxFifoFreeLevel(&can1) != 0U) {
            send = HAL_FDCAN_AddMessageToTxFifoQ(&can1, &tx, payload);
        }
        diag_sequence = sequence;
        diag_detail = (uint32_t)send;
        diag_phase = 6U;
        tx_probe_wait_ms(200U);
        while (HAL_FDCAN_GetRxFifoFillLevel(&can1, FDCAN_RX_FIFO0) != 0U) {
            FDCAN_RxHeaderTypeDef rx = {0};
            uint8_t rx_data[64] = {0};
            if (HAL_FDCAN_GetRxMessage(&can1, FDCAN_RX_FIFO0, &rx, rx_data) != HAL_OK) {
                break;
            }
            ++rx_count;
            (void)snprintf(line, sizeof(line),
                           "CAN RX id=%03lX len=%lu b0=%02X count=%lu\r\n",
                           (unsigned long)rx.Identifier,
                           (unsigned long)rx.DataLength,
                           (unsigned)rx_data[0],
                           (unsigned long)rx_count);
            console_write(line);
        }
        (void)HAL_FDCAN_GetErrorCounters(&can1, &errors);
        (void)HAL_FDCAN_GetProtocolStatus(&can1, &status);
        (void)snprintf(line, sizeof(line),
                       "CAN RAM seq=%lu enqueue=%u TXBTO=%lX TEC=%lu REC=%lu BO=%lu LEC=%lu SD=0\r\n",
                       (unsigned long)sequence, (unsigned)send,
                       (unsigned long)FDCAN1->TXBTO,
                       (unsigned long)errors.TxErrorCnt,
                       (unsigned long)errors.RxErrorCnt,
                       (unsigned long)status.BusOff,
                       (unsigned long)status.LastErrorCode);
        console_write(line);
        if (status.BusOff != 0U) {
            break;
        }
        tx_probe_wait_ms(800U);
    }
    (void)HAL_FDCAN_Stop(&can1);
    diag_phase = 7U;
    stop_forever("CAN RAM DIAG DONE: CAN stopped; SD=0\r\n");
#endif
#endif
}
