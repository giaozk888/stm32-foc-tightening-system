#include "modbus_probe.h"

#include <string.h>

#include "stm32g4xx_hal.h"
#include "FreeRTOS.h"
#include "task.h"

static UART_HandleTypeDef modbus_uart;
static DMA_HandleTypeDef modbus_rx_dma;
static uint8_t modbus_gpio_initialized;
static uint8_t modbus_dma_initialized;

#define MODBUS_RX_DMA_CAPACITY  (16U)

static HAL_StatusTypeDef Modbus_DmaInit(void)
{
    if (modbus_dma_initialized != 0U)
    {
        return HAL_OK;
    }

    __HAL_RCC_DMAMUX1_CLK_ENABLE();
    __HAL_RCC_DMA1_CLK_ENABLE();
    memset(&modbus_rx_dma, 0, sizeof(modbus_rx_dma));
    modbus_rx_dma.Instance = DMA1_Channel3;
    modbus_rx_dma.Init.Request = DMA_REQUEST_USART3_RX;
    modbus_rx_dma.Init.Direction = DMA_PERIPH_TO_MEMORY;
    modbus_rx_dma.Init.PeriphInc = DMA_PINC_DISABLE;
    modbus_rx_dma.Init.MemInc = DMA_MINC_ENABLE;
    modbus_rx_dma.Init.PeriphDataAlignment = DMA_PDATAALIGN_BYTE;
    modbus_rx_dma.Init.MemDataAlignment = DMA_MDATAALIGN_BYTE;
    modbus_rx_dma.Init.Mode = DMA_CIRCULAR;
    modbus_rx_dma.Init.Priority = DMA_PRIORITY_LOW;
    if (HAL_DMA_Init(&modbus_rx_dma) != HAL_OK)
    {
        return HAL_ERROR;
    }
    __HAL_LINKDMA(&modbus_uart, hdmarx, modbus_rx_dma);
    modbus_dma_initialized = 1U;
    return HAL_OK;
}

/* RX DMA starts before TX, so even a prompt slave response is not missed.
 * No DMA IRQ is required: the low-priority ModbusTask samples NDTR and yields.
 * A 16-byte circular buffer is larger than every supported 5-8 byte reply. */
static ModbusProbeResult_t Modbus_Exchange(const uint8_t request[8],
                                          uint8_t response[MODBUS_RX_DMA_CAPACITY],
                                          uint8_t slave,
                                          uint8_t function,
                                          uint8_t relay_write,
                                          uint8_t *expected_length,
                                          ModbusProbeReply_t *reply)
{
    HAL_StatusTypeDef status;
    uint32_t started;
    uint8_t count = 0U;
    uint8_t expected = 0U;
    ModbusProbeResult_t result = MODBUS_PROBE_TIMEOUT;

    if (Modbus_DmaInit() != HAL_OK)
    {
        return MODBUS_PROBE_UART_ERROR;
    }
    memset(response, 0, MODBUS_RX_DMA_CAPACITY);
    status = HAL_UART_Receive_DMA(&modbus_uart, response,
                                  MODBUS_RX_DMA_CAPACITY);
    if (status != HAL_OK)
    {
        reply->uart_error = HAL_UART_GetError(&modbus_uart);
        return MODBUS_PROBE_UART_ERROR;
    }
    __HAL_DMA_DISABLE_IT(&modbus_rx_dma,
                         DMA_IT_HT | DMA_IT_TC | DMA_IT_TE);

    status = HAL_UART_Transmit(&modbus_uart, (uint8_t *)request, 8U, 30U);
    if (status != HAL_OK)
    {
        reply->uart_error = HAL_UART_GetError(&modbus_uart);
        (void)HAL_UART_AbortReceive(&modbus_uart);
        return MODBUS_PROBE_UART_ERROR;
    }

    started = HAL_GetTick();
    while ((HAL_GetTick() - started) < 150U)
    {
        uint32_t uart_flags = modbus_uart.Instance->ISR &
            (USART_ISR_ORE | USART_ISR_FE | USART_ISR_NE | USART_ISR_PE);
        if (uart_flags != 0U)
        {
            reply->uart_error = uart_flags;
            result = MODBUS_PROBE_UART_ERROR;
            break;
        }
        count = (uint8_t)(MODBUS_RX_DMA_CAPACITY -
                          __HAL_DMA_GET_COUNTER(&modbus_rx_dma));
        if (count >= 2U)
        {
            if ((response[0] != slave) ||
                ((response[1] != function) &&
                 (response[1] != (uint8_t)(function | 0x80U))))
            {
                result = MODBUS_PROBE_BAD_FRAME;
                break;
            }
            if ((response[1] & 0x80U) != 0U)
            {
                expected = 5U;
            }
            else if (relay_write != 0U)
            {
                expected = 8U;
            }
            else if (count >= 3U)
            {
                expected = function <= 2U ? 6U : 7U;
                if (response[2] != (uint8_t)(expected - 5U))
                {
                    result = MODBUS_PROBE_BAD_FRAME;
                    break;
                }
            }
            if ((expected != 0U) && (count >= expected))
            {
                result = MODBUS_PROBE_OK;
                break;
            }
        }
        vTaskDelay(pdMS_TO_TICKS(1U));
    }

    reply->received_bytes = count;
    if (HAL_UART_AbortReceive(&modbus_uart) != HAL_OK)
    {
        reply->uart_error = HAL_UART_GetError(&modbus_uart);
        return MODBUS_PROBE_UART_ERROR;
    }
    if (result == MODBUS_PROBE_OK)
    {
        *expected_length = expected;
        reply->received_bytes = expected;
    }
    return result;
}

static uint16_t Modbus_Crc16(const uint8_t *bytes, uint8_t length)
{
    uint16_t crc = 0xffffU;
    uint8_t i;

    for (i = 0U; i < length; ++i)
    {
        uint8_t bit;
        crc ^= bytes[i];
        for (bit = 0U; bit < 8U; ++bit)
        {
            crc = (uint16_t)((crc >> 1U) ^
                             ((crc & 1U) != 0U ? 0xa001U : 0U));
        }
    }
    return crc;
}

static HAL_StatusTypeDef Modbus_UartInit(uint32_t baud, uint8_t even_parity)
{
    if (modbus_gpio_initialized == 0U)
    {
        GPIO_InitTypeDef gpio = {0};

        __HAL_RCC_GPIOC_CLK_ENABLE();
        __HAL_RCC_USART3_CLK_ENABLE();
        gpio.Pin = GPIO_PIN_10 | GPIO_PIN_11;
        gpio.Mode = GPIO_MODE_AF_PP;
        gpio.Pull = GPIO_PULLUP;
        gpio.Speed = GPIO_SPEED_FREQ_MEDIUM;
        gpio.Alternate = GPIO_AF7_USART3;
        HAL_GPIO_Init(GPIOC, &gpio);
        modbus_gpio_initialized = 1U;
    }

    modbus_uart.Instance = USART3;
    modbus_uart.Init.BaudRate = baud;
    modbus_uart.Init.WordLength = even_parity != 0U ?
        UART_WORDLENGTH_9B : UART_WORDLENGTH_8B;
    modbus_uart.Init.StopBits = UART_STOPBITS_1;
    modbus_uart.Init.Parity = even_parity != 0U ?
        UART_PARITY_EVEN : UART_PARITY_NONE;
    modbus_uart.Init.Mode = UART_MODE_TX_RX;
    modbus_uart.Init.HwFlowCtl = UART_HWCONTROL_NONE;
    modbus_uart.Init.OverSampling = UART_OVERSAMPLING_16;
    modbus_uart.Init.OneBitSampling = UART_ONE_BIT_SAMPLE_DISABLE;
    modbus_uart.Init.ClockPrescaler = UART_PRESCALER_DIV1;
    modbus_uart.AdvancedInit.AdvFeatureInit = UART_ADVFEATURE_NO_INIT;
    return HAL_UART_Init(&modbus_uart);
}

ModbusProbeResult_t ModbusProbe_ReadOne(uint32_t baud,
                                      uint8_t slave,
                                      uint8_t function,
                                      uint16_t address,
                                      uint8_t even_parity,
                                      ModbusProbeReply_t *reply)
{
    uint8_t request[8];
    uint8_t response[MODBUS_RX_DMA_CAPACITY] = {0};
    uint8_t expected_length = 0U;
    uint16_t crc;
    HAL_StatusTypeDef status;
    ModbusProbeResult_t result;

    if (reply == NULL)
    {
        return MODBUS_PROBE_BAD_ARGUMENT;
    }
    memset(reply, 0, sizeof(*reply));
    if (((function < 1U) || (function > 4U)) ||
        (slave == 0U) || ((slave > 247U) && (slave != 255U)) ||
        ((baud != 9600U) && (baud != 19200U) &&
         (baud != 38400U) && (baud != 57600U) &&
         (baud != 115200U)) || (even_parity > 1U))
    {
        return MODBUS_PROBE_BAD_ARGUMENT;
    }

    status = Modbus_UartInit(baud, even_parity);
    if (status != HAL_OK)
    {
        reply->uart_error = HAL_UART_GetError(&modbus_uart);
        return MODBUS_PROBE_UART_ERROR;
    }

    /* Function 1/2 reads eight coils/inputs; 3/4 reads one register. */
    request[0] = slave;
    request[1] = function;
    request[2] = (uint8_t)(address >> 8U);
    request[3] = (uint8_t)address;
    request[4] = 0U;
    request[5] = function <= 2U ? 8U : 1U;
    crc = Modbus_Crc16(request, 6U);
    request[6] = (uint8_t)crc;
    request[7] = (uint8_t)(crc >> 8U);

    result = Modbus_Exchange(request, response, slave, function, 0U,
                             &expected_length, reply);
    if (result != MODBUS_PROBE_OK)
    {
        return result;
    }
    crc = Modbus_Crc16(response, expected_length - 2U);
    if ((response[expected_length - 2U] != (uint8_t)crc) ||
        (response[expected_length - 1U] != (uint8_t)(crc >> 8U)))
    {
        return MODBUS_PROBE_CRC_ERROR;
    }
    if (expected_length == 5U)
    {
        reply->exception_code = response[2];
        return MODBUS_PROBE_EXCEPTION;
    }

    reply->value = expected_length == 6U ? response[3] :
        ((uint16_t)response[3] << 8U) | response[4];
    return MODBUS_PROBE_OK;
}

ModbusProbeResult_t ModbusProbe_SetRelay(uint8_t relay,
                                       uint8_t on,
                                       ModbusProbeReply_t *reply)
{
    uint8_t request[8] = {255U, 5U, 0U, 0U, 0U, 0U, 0U, 0U};
    uint8_t response[MODBUS_RX_DMA_CAPACITY] = {0};
    uint8_t expected_length = 0U;
    uint16_t crc;
    HAL_StatusTypeDef status;
    ModbusProbeResult_t result;

    if (reply == NULL)
    {
        return MODBUS_PROBE_BAD_ARGUMENT;
    }
    memset(reply, 0, sizeof(*reply));
    if ((relay < 1U) || (relay > 4U) || (on > 1U))
    {
        return MODBUS_PROBE_BAD_ARGUMENT;
    }
    status = Modbus_UartInit(9600U, 0U);
    if (status != HAL_OK)
    {
        reply->uart_error = HAL_UART_GetError(&modbus_uart);
        return MODBUS_PROBE_UART_ERROR;
    }

    request[3] = relay - 1U;
    request[4] = on != 0U ? 0xffU : 0U;
    crc = Modbus_Crc16(request, 6U);
    request[6] = (uint8_t)crc;
    request[7] = (uint8_t)(crc >> 8U);
    result = Modbus_Exchange(request, response, 255U, 5U, 1U,
                             &expected_length, reply);
    if (result != MODBUS_PROBE_OK)
    {
        return result;
    }
    crc = Modbus_Crc16(response, expected_length - 2U);
    if ((response[expected_length - 2U] != (uint8_t)crc) ||
        (response[expected_length - 1U] != (uint8_t)(crc >> 8U)))
    {
        return MODBUS_PROBE_CRC_ERROR;
    }
    if (expected_length == 5U)
    {
        reply->exception_code = response[2];
        return MODBUS_PROBE_EXCEPTION;
    }
    if (memcmp(request, response, sizeof(request)) != 0)
    {
        return MODBUS_PROBE_BAD_FRAME;
    }

    reply->value = on;
    return MODBUS_PROBE_OK;
}
