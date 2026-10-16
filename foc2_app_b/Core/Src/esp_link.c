#include "esp_link.h"
#include "esp_ping.h"
#if defined(ROUTER_READ_ONLY_NETWORK)
#include "router_network.h"
#if defined(ROUTER_READ_ONLY_RPC)
#include "router_rpc_wire.h"
#endif
#if defined(ROUTER_READ_ONLY_TRANSFER)
#include "router_transfer_wire.h"
#endif
#endif

#include <stdio.h>
#include <string.h>

#include "stm32g4xx_hal.h"
#include "FreeRTOS.h"
#include "queue.h"
#include "task.h"

#define ESP_LINK_BAUD                 115200U
#define ESP_LINK_NODE_ID             2U
#define ESP_LINK_RX_DEPTH            512U
#define ESP_LINK_TX_DEPTH            4U
#define ESP_LINK_MAX_LINE            (ROUTER_MAX_PAYLOAD + 96U)

typedef struct
{
    uint16_t length;
    char bytes[ESP_LINK_MAX_LINE + 2U];
} EspLinkTxLine_t;

static UART_HandleTypeDef g_esp_uart;
static QueueHandle_t g_rx_queue;
static QueueHandle_t g_tx_queue;
static volatile uint32_t g_rx_overflow;
static volatile uint32_t g_uart_errors;
static uint8_t g_ready;

static uint8_t EspLink_IsAllowedIngress(const char *line)
{
#if defined(ROUTER_READ_ONLY_NETWORK)
    /* Only numeric diagnostics and exact discovery are added. The legacy
     * PROTOCOL ingress below stays restricted to node-2 PONG replies. */
    if (rn_line_allowed(line)) return 1U;
#endif
    unsigned int src, dst, type, seq, ttl, length;
    int payload_offset = 0;
    const char *payload;
    uint16_t ping_request_id;

    if ((line == NULL) || (strncmp(line, "@R1 ", 4U) != 0))
    {
        return 0U;
    }
    if (sscanf(line, "@R1 %u %u %u %u %u %u %n",
               &src, &dst, &type, &seq, &ttl, &length,
               &payload_offset) != 6)
    {
        return 0U;
    }
    if ((src != ESP_LINK_NODE_ID) ||
        ((dst != 1U) && (dst != ROUTER_BROADCAST_NODE)) ||
        (seq > 0xFFFFU) || (ttl == 0U) || (ttl > 8U) ||
        (payload_offset <= 0) ||
        (payload_offset >= (int)ESP_LINK_MAX_LINE))
    {
        return 0U;
    }
    payload = line + payload_offset;
    if (strlen(payload) != (size_t)length)
    {
        return 0U;
    }
    if (type == ROUTER_PKT_DISCOVERY)
    {
        return ((strcmp(payload, ROUTER_DISCOVERY_HELLO_TEXT) == 0) ||
                (strcmp(payload, ROUTER_DISCOVERY_ANNOUNCE_TEXT) == 0)) ? 1U : 0U;
    }
    if ((type == ROUTER_PKT_PROTOCOL) && (dst == 1U))
    {
        return EspPing_ParsePongPayload(payload, &ping_request_id);
    }
    return 0U;
}

uint8_t EspLink_Init(void)
{
    GPIO_InitTypeDef gpio = {0};

    if (g_ready != 0U)
    {
        return 1U;
    }
    g_rx_queue = xQueueCreate(ESP_LINK_RX_DEPTH, sizeof(uint8_t));
    g_tx_queue = xQueueCreate(ESP_LINK_TX_DEPTH, sizeof(EspLinkTxLine_t));
    if ((g_rx_queue == NULL) || (g_tx_queue == NULL))
    {
        if (g_rx_queue != NULL) vQueueDelete(g_rx_queue);
        if (g_tx_queue != NULL) vQueueDelete(g_tx_queue);
        g_rx_queue = NULL;
        g_tx_queue = NULL;
        return 0U;
    }

    __HAL_RCC_GPIOA_CLK_ENABLE();
    __HAL_RCC_USART1_CLK_ENABLE();
    gpio.Pin = GPIO_PIN_9 | GPIO_PIN_10;
    gpio.Mode = GPIO_MODE_AF_PP;
    gpio.Pull = GPIO_PULLUP;
    gpio.Speed = GPIO_SPEED_FREQ_MEDIUM;
    gpio.Alternate = GPIO_AF7_USART1;
    HAL_GPIO_Init(GPIOA, &gpio);

    g_esp_uart.Instance = USART1;
    g_esp_uart.Init.BaudRate = ESP_LINK_BAUD;
    g_esp_uart.Init.WordLength = UART_WORDLENGTH_8B;
    g_esp_uart.Init.StopBits = UART_STOPBITS_1;
    g_esp_uart.Init.Parity = UART_PARITY_NONE;
    g_esp_uart.Init.Mode = UART_MODE_TX_RX;
    g_esp_uart.Init.HwFlowCtl = UART_HWCONTROL_NONE;
    g_esp_uart.Init.OverSampling = UART_OVERSAMPLING_16;
    g_esp_uart.Init.OneBitSampling = UART_ONE_BIT_SAMPLE_DISABLE;
    g_esp_uart.Init.ClockPrescaler = UART_PRESCALER_DIV1;
    g_esp_uart.AdvancedInit.AdvFeatureInit = UART_ADVFEATURE_NO_INIT;
    if (HAL_UART_Init(&g_esp_uart) != HAL_OK)
    {
        vQueueDelete(g_rx_queue);
        vQueueDelete(g_tx_queue);
        g_rx_queue = NULL;
        g_tx_queue = NULL;
        return 0U;
    }

    USART1->ICR = USART_ICR_ORECF | USART_ICR_FECF |
                  USART_ICR_NECF | USART_ICR_PECF;
    HAL_NVIC_SetPriority(USART1_IRQn, 6U, 0U);
    HAL_NVIC_EnableIRQ(USART1_IRQn);
    SET_BIT(USART1->CR1, USART_CR1_RXNEIE_RXFNEIE);
    g_ready = 1U;
    return 1U;
}

void EspLink_Deinit(void)
{
    CLEAR_BIT(USART1->CR1, USART_CR1_RXNEIE_RXFNEIE);
    HAL_NVIC_DisableIRQ(USART1_IRQn);
    (void)HAL_UART_DeInit(&g_esp_uart);
    HAL_GPIO_DeInit(GPIOA, GPIO_PIN_9 | GPIO_PIN_10);
    __HAL_RCC_USART1_CLK_DISABLE();
    g_ready = 0U;
    if (g_rx_queue != NULL) vQueueDelete(g_rx_queue);
    if (g_tx_queue != NULL) vQueueDelete(g_tx_queue);
    g_rx_queue = NULL;
    g_tx_queue = NULL;
}

/* The dedicated ESP UART never carries COM5 diagnostics or raw commands.
 * Queue copies own each line. RPC producers may wait a bounded 30 ms for the
 * dedicated consumer; all existing packet types keep their nonblocking send. */
uint8_t EspLink_RouterTx(const RouterPacket_t *packet)
{
    EspLinkTxLine_t tx = {0};
    size_t length;

    if ((g_ready == 0U) || (g_tx_queue == NULL))
    {
        return 0U;
    }
    length = Router_EncodeAsciiFrame(packet, tx.bytes,
                                     sizeof(tx.bytes) - 2U);
    if (length == 0U)
    {
        return 0U;
    }
    tx.bytes[length++] = '\r';
    tx.bytes[length++] = '\n';
    tx.length = (uint16_t)length;
#if defined(ROUTER_READ_ONLY_RPC)
    /* Two clients can complete 8 unary calls before this 4-slot queue drains.
     * Apply bounded backpressure, not a heap-expanding queue or blind retry.
     * Router/Protocol tasks run below control; never call from an ISR. */
    TickType_t wait = packet->type == RN_RPC_TYPE ? pdMS_TO_TICKS(30U) : 0U;
#if defined(ROUTER_READ_ONLY_TRANSFER)
    if (packet->type == RN_TRANSFER_TYPE) wait = pdMS_TO_TICKS(30U);
#endif
    return (xQueueSend(g_tx_queue, &tx, wait) == pdPASS) ? 1U : 0U;
#else
    return (xQueueSend(g_tx_queue, &tx, 0U) == pdPASS) ? 1U : 0U;
#endif
}

void EspLink_Task(void *argument)
{
    char line[ESP_LINK_MAX_LINE + 1U];
    size_t line_length = 0U;
    uint8_t dropping = 0U;
    EspLinkTxLine_t tx;
    uint8_t ch;

    (void)argument;
    for (;;)
    {
        if (xQueueReceive(g_tx_queue, &tx, 0U) == pdPASS)
        {
            (void)HAL_UART_Transmit(&g_esp_uart, (uint8_t *)tx.bytes,
                                    tx.length, 100U);
        }

        if (xQueueReceive(g_rx_queue, &ch, pdMS_TO_TICKS(5U)) != pdPASS)
        {
            continue;
        }
        do
        {
            if ((ch == '\r') || (ch == '\n'))
            {
                if ((dropping == 0U) && (line_length != 0U))
                {
                    line[line_length] = '\0';
                    /* Discovery, exact ESP32 PONG and opt-in numeric Router
                     * diagnostics only. Motor/parameter/IAP remain closed. */
                    if (EspLink_IsAllowedIngress(line) != 0U)
                    {
                        (void)Router_SubmitAsciiLine(ROUTER_PORT_ESP32,
                                                     line);
                    }
                }
                line_length = 0U;
                dropping = 0U;
            }
            else if ((ch >= 0x20U) && (ch <= 0x7EU) &&
                     (dropping == 0U))
            {
                if (line_length < ESP_LINK_MAX_LINE)
                {
                    line[line_length++] = (char)ch;
                }
                else
                {
                    line_length = 0U;
                    dropping = 1U;
                }
            }
            else
            {
                line_length = 0U;
                dropping = 1U;
            }
        } while (xQueueReceive(g_rx_queue, &ch, 0U) == pdPASS);
    }
}

void USART1_IRQHandler(void)
{
    BaseType_t woken = pdFALSE;
    const uint32_t flags = USART1->ISR;

    if ((flags & (USART_ISR_ORE | USART_ISR_FE |
                  USART_ISR_NE | USART_ISR_PE)) != 0U)
    {
        USART1->ICR = USART_ICR_ORECF | USART_ICR_FECF |
                      USART_ICR_NECF | USART_ICR_PECF;
        g_uart_errors++;
    }
    while ((USART1->ISR & USART_ISR_RXNE_RXFNE) != 0U)
    {
        const uint8_t ch = (uint8_t)USART1->RDR;
        if ((g_rx_queue == NULL) ||
            (xQueueSendFromISR(g_rx_queue, &ch, &woken) != pdPASS))
        {
            g_rx_overflow++;
        }
    }
    portYIELD_FROM_ISR(woken);
}
