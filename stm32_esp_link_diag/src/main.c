#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

#include "stm32g4xx_hal.h"

/* Communication-only B-slot image. No TIM1, ADC, SPI, FOC or FreeRTOS init. */
static UART_HandleTypeDef console_uart;
static UART_HandleTypeDef esp_uart;
static uint32_t rx_hello_count;
static uint32_t rx_pong_count;
static uint32_t rx_invalid_count;
static uint32_t tx_hello_count;
static uint32_t tx_error_count;
static uint32_t next_sequence = 1U;

static void power_stage_off(void)
{
    __HAL_RCC_GPIOC_CLK_ENABLE();
    /* Set output latch low before switching PC6 to output mode. */
    GPIOC->BSRR = GPIO_BSRR_BR6;
    GPIO_InitTypeDef pin = {0};
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

static bool init_uart(UART_HandleTypeDef *uart, USART_TypeDef *instance)
{
    memset(uart, 0, sizeof(*uart));
    uart->Instance = instance;
    uart->Init.BaudRate = 115200U;
    uart->Init.WordLength = UART_WORDLENGTH_8B;
    uart->Init.StopBits = UART_STOPBITS_1;
    uart->Init.Parity = UART_PARITY_NONE;
    uart->Init.Mode = UART_MODE_TX_RX;
    uart->Init.HwFlowCtl = UART_HWCONTROL_NONE;
    uart->Init.OverSampling = UART_OVERSAMPLING_16;
    uart->Init.OneBitSampling = UART_ONE_BIT_SAMPLE_DISABLE;
    uart->Init.ClockPrescaler = UART_PRESCALER_DIV1;
    return HAL_UART_Init(uart) == HAL_OK;
}

void HAL_UART_MspInit(UART_HandleTypeDef *uart)
{
    GPIO_InitTypeDef pin = {0};
    __HAL_RCC_GPIOA_CLK_ENABLE();
    pin.Mode = GPIO_MODE_AF_PP;
    pin.Pull = GPIO_NOPULL;
    pin.Speed = GPIO_SPEED_FREQ_LOW;
    if (uart->Instance == LPUART1) {
        __HAL_RCC_LPUART1_CLK_ENABLE();
        pin.Pin = GPIO_PIN_2 | GPIO_PIN_3;
        pin.Alternate = GPIO_AF12_LPUART1;
    } else if (uart->Instance == USART1) {
        __HAL_RCC_USART1_CLK_ENABLE();
        pin.Pin = GPIO_PIN_9 | GPIO_PIN_10;
        pin.Alternate = GPIO_AF7_USART1;
    } else {
        return;
    }
    HAL_GPIO_Init(GPIOA, &pin);
}

void SysTick_Handler(void)
{
    HAL_IncTick();
}

static bool is_esp_hello(const char *line)
{
    unsigned src, dst, type, seq, ttl, length;
    char payload[8] = {0};
    char trailing;
    const int fields = sscanf(line, "@R1 %u %u %u %u %u %u %7s %c",
                              &src, &dst, &type, &seq, &ttl, &length,
                              payload, &trailing);
    (void)seq;
    return fields == 7 && src == 2U && (dst == 1U || dst == 65535U) &&
           type == 3U && ttl > 0U && ttl <= 255U && length == 5U &&
           strcmp(payload, "HELLO") == 0;
}

static bool is_esp_pong(const char *line)
{
    unsigned src, dst, type, seq, ttl, length;
    int payload_offset = 0;
    const int fields = sscanf(line, "@R1 %u %u %u %u %u %u %n",
                              &src, &dst, &type, &seq, &ttl, &length,
                              &payload_offset);
    (void)seq;
    return fields == 6 && payload_offset > 0 && src == 2U && dst == 1U &&
           type == 1U && ttl > 0U && ttl <= 255U && length == 16U &&
           strcmp(line + payload_offset, "42 OK ESP32 PONG") == 0;
}

static void send_frame(uint8_t type, const char *payload)
{
    char frame[80];
    const int used = snprintf(frame, sizeof(frame),
                              "@R1 1 2 %u %lu 8 %u %s\r\n",
                              (unsigned)type, (unsigned long)next_sequence++,
                              (unsigned)strlen(payload), payload);
    if (used > 0 && (size_t)used < sizeof(frame)) {
        if (HAL_UART_Transmit(&esp_uart, (uint8_t *)frame,
                              (uint16_t)used, 100U) == HAL_OK) {
            ++tx_hello_count;
        } else {
            ++tx_error_count;
        }
    } else {
        ++tx_error_count;
    }
}

int main(void)
{
    char line[96];
    size_t length = 0U;
    bool dropping = false;
    uint32_t last_report;
    uint32_t last_hello;

    SCB->VTOR = DIAG_VECTOR_BASE;
    HAL_Init();
    power_stage_off();
    /* Reset HSI16 clock, 115200 8N1. LPUART1=PA2/PA3 (COM5),
     * USART1=PA9/PA10 (ESP32); power stage remains disabled. */
    if (!init_uart(&console_uart, LPUART1) ||
        !init_uart(&esp_uart, USART1)) {
        for (;;) {
            power_stage_off();
        }
    }
    console_write("STM32 ESP-LINK DIAG: COMM ONLY; PC6 SD=0; PWM/FOC OFF\r\n");
    last_report = HAL_GetTick();
    last_hello = last_report;
    send_frame(3U, "HELLO");
    send_frame(1U, "42 PING");

    for (;;) {
        uint8_t ch;
        power_stage_off();
        if (HAL_UART_Receive(&esp_uart, &ch, 1U, 20U) == HAL_OK) {
            if (ch == '\r' || ch == '\n') {
                if (!dropping && length != 0U) {
                    line[length] = '\0';
                    if (is_esp_hello(line)) {
                        ++rx_hello_count;
                        console_write("ESP HELLO RX OK\r\n");
                    } else if (is_esp_pong(line)) {
                        ++rx_pong_count;
                        console_write("ESP PONG RX OK\r\n");
                    } else {
                        ++rx_invalid_count;
                    }
                }
                length = 0U;
                dropping = false;
            } else if (ch >= 0x20U && ch <= 0x7eU && !dropping) {
                if (length < sizeof(line) - 1U) {
                    line[length++] = (char)ch;
                } else {
                    length = 0U;
                    dropping = true;
                    ++rx_invalid_count;
                }
            }
        }
        const uint32_t now = HAL_GetTick();
        if (now - last_hello >= 5000U) {
            send_frame(3U, "HELLO");
            send_frame(1U, "42 PING");
            last_hello = now;
        }
        if (now - last_report >= 5000U) {
            char status[160];
            (void)snprintf(status, sizeof(status),
                           "DIAG SD=0 PWM=OFF TX_OK=%lu TX_FAIL=%lu ESP_HELLO=%lu ESP_PONG=%lu RX_OTHER=%lu\r\n",
                           (unsigned long)tx_hello_count,
                           (unsigned long)tx_error_count,
                           (unsigned long)rx_hello_count,
                           (unsigned long)rx_pong_count,
                           (unsigned long)rx_invalid_count);
            console_write(status);
            last_report = now;
        }
    }
}
