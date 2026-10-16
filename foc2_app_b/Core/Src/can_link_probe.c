#include "can_link_probe.h"

#include <stdio.h>
#include <string.h>

#include "main.h"

/* 170 MHz PCLK1 / (17 * (1 + 16 + 3)) = 500 kbit/s, sample point 85%. */
static FDCAN_HandleTypeDef can1;

static void Probe_Print(UART_HandleTypeDef *uart, const char *message)
{
    (void)HAL_UART_Transmit(uart, (uint8_t *)message,
                            (uint16_t)strlen(message), 100U);
}

void HAL_FDCAN_MspInit(FDCAN_HandleTypeDef *hfdcan)
{
    GPIO_InitTypeDef gpio = {0};

    if (hfdcan->Instance != FDCAN1)
    {
        return;
    }

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
    if (hfdcan->Instance != FDCAN1)
    {
        return;
    }

    HAL_GPIO_DeInit(GPIOB, GPIO_PIN_8 | GPIO_PIN_9);
    __HAL_RCC_FDCAN_CLK_DISABLE();
}

__attribute__((noreturn)) void CAN_LinkProbe_RunForever(UART_HandleTypeDef *uart)
{
    RCC_PeriphCLKInitTypeDef clock = {0};
    FDCAN_TxHeaderTypeDef tx = {0};
    uint8_t payload[8] = {'C', 'A', 'N', '1', 0U, 0U, 0U, 0U};
    uint32_t sequence = 0U;
    char line[160];

    HAL_GPIO_WritePin(DRIVER_SD_GPIO_Port, DRIVER_SD_Pin, GPIO_PIN_RESET);
    Probe_Print(uart, "CAN PROBE ONLY: bridge disabled, no motor tasks\r\n");

    clock.PeriphClockSelection = RCC_PERIPHCLK_FDCAN;
    clock.FdcanClockSelection = RCC_FDCANCLKSOURCE_PCLK1;
    if (HAL_RCCEx_PeriphCLKConfig(&clock) != HAL_OK)
    {
        Probe_Print(uart, "CAN PROBE: clock setup FAILED\r\n");
        goto stopped;
    }

    can1.Instance = FDCAN1;
    can1.Init.ClockDivider = FDCAN_CLOCK_DIV1;
    can1.Init.FrameFormat = FDCAN_FRAME_CLASSIC;
    can1.Init.Mode = FDCAN_MODE_NORMAL;
    can1.Init.AutoRetransmission = DISABLE;
    can1.Init.TransmitPause = DISABLE;
    can1.Init.ProtocolException = ENABLE;
    can1.Init.NominalPrescaler = 17U;
    can1.Init.NominalSyncJumpWidth = 2U;
    can1.Init.NominalTimeSeg1 = 16U;
    can1.Init.NominalTimeSeg2 = 3U;
    can1.Init.DataPrescaler = 1U;
    can1.Init.DataSyncJumpWidth = 1U;
    can1.Init.DataTimeSeg1 = 1U;
    can1.Init.DataTimeSeg2 = 1U;
    can1.Init.StdFiltersNbr = 0U;
    can1.Init.ExtFiltersNbr = 0U;
    can1.Init.TxFifoQueueMode = FDCAN_TX_FIFO_OPERATION;

    if (HAL_FDCAN_Init(&can1) != HAL_OK)
    {
        Probe_Print(uart, "CAN PROBE: FDCAN init FAILED\r\n");
        goto stopped;
    }

    /* No receive filter or command path is installed in this test image. */
    if (HAL_FDCAN_ConfigGlobalFilter(&can1, FDCAN_REJECT, FDCAN_REJECT,
                                     FDCAN_REJECT_REMOTE,
                                     FDCAN_REJECT_REMOTE) != HAL_OK)
    {
        Probe_Print(uart, "CAN PROBE: reject filter FAILED\r\n");
        goto stopped;
    }

    tx.Identifier = 0x701U;
    tx.IdType = FDCAN_STANDARD_ID;
    tx.TxFrameType = FDCAN_DATA_FRAME;
    tx.DataLength = FDCAN_DLC_BYTES_8;
    tx.ErrorStateIndicator = FDCAN_ESI_ACTIVE;
    tx.BitRateSwitch = FDCAN_BRS_OFF;
    tx.FDFormat = FDCAN_CLASSIC_CAN;
    tx.TxEventFifoControl = FDCAN_NO_TX_EVENTS;

    if (HAL_FDCAN_Start(&can1) != HAL_OK)
    {
        Probe_Print(uart, "CAN PROBE: FDCAN start FAILED\r\n");
        goto stopped;
    }

    Probe_Print(uart, "CAN PROBE: PB8 RX / PB9 TX, 500k classic, ID 701\r\n");

    for (;;)
    {
        FDCAN_ErrorCountersTypeDef errors = {0};
        FDCAN_ProtocolStatusTypeDef status = {0};
        HAL_StatusTypeDef send = HAL_BUSY;

        /* The dedicated probe never enables the motor bridge. */
        HAL_GPIO_WritePin(DRIVER_SD_GPIO_Port, DRIVER_SD_Pin, GPIO_PIN_RESET);
        payload[4] = (uint8_t)(sequence >> 24);
        payload[5] = (uint8_t)(sequence >> 16);
        payload[6] = (uint8_t)(sequence >> 8);
        payload[7] = (uint8_t)sequence;

        if (HAL_FDCAN_GetTxFifoFreeLevel(&can1) != 0U)
        {
            send = HAL_FDCAN_AddMessageToTxFifoQ(&can1, &tx, payload);
        }

        (void)HAL_FDCAN_GetErrorCounters(&can1, &errors);
        (void)HAL_FDCAN_GetProtocolStatus(&can1, &status);
        (void)snprintf(line, sizeof(line),
                       "CAN PROBE seq=%lu enqueue=%u TEC=%lu REC=%lu BO=%lu LEC=%lu SD=0\r\n",
                       (unsigned long)sequence, (unsigned int)send,
                       (unsigned long)errors.TxErrorCnt,
                       (unsigned long)errors.RxErrorCnt,
                       (unsigned long)status.BusOff,
                       (unsigned long)status.LastErrorCode);
        Probe_Print(uart, line);
        ++sequence;
        HAL_Delay(1000U);
    }

stopped:
    for (;;)
    {
        HAL_GPIO_WritePin(DRIVER_SD_GPIO_Port, DRIVER_SD_Pin, GPIO_PIN_RESET);
        HAL_Delay(1000U);
    }
}
