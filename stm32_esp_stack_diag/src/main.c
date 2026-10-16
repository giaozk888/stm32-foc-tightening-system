#include <stdint.h>
#include <stdio.h>
#include <string.h>

#include "stm32g4xx_hal.h"
#include "FreeRTOS.h"
#include "task.h"
#include "esp_link.h"
#include "router.h"

/* Test the exact A-slot esp_link.c and router.c from SRAM. No motor init. */
static UART_HandleTypeDef console_uart;
static volatile uint8_t scheduler_started;

static void button_input_init(void)
{
    GPIO_InitTypeDef pin = {0};
    __HAL_RCC_GPIOC_CLK_ENABLE();
    pin.Pin = GPIO_PIN_13;
    pin.Mode = GPIO_MODE_INPUT;
    pin.Pull = GPIO_PULLDOWN;
    HAL_GPIO_Init(GPIOC, &pin);
}

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

void HAL_UART_MspInit(UART_HandleTypeDef *uart)
{
    GPIO_InitTypeDef pin = {0};
    if (uart->Instance != LPUART1) {
        return;
    }
    __HAL_RCC_GPIOA_CLK_ENABLE();
    __HAL_RCC_LPUART1_CLK_ENABLE();
    pin.Pin = GPIO_PIN_2 | GPIO_PIN_3;
    pin.Mode = GPIO_MODE_AF_PP;
    pin.Pull = GPIO_NOPULL;
    pin.Speed = GPIO_SPEED_FREQ_LOW;
    pin.Alternate = GPIO_AF12_LPUART1;
    HAL_GPIO_Init(GPIOA, &pin);
}

extern void xPortSysTickHandler(void);

void SysTick_Handler(void)
{
    HAL_IncTick();
    if (scheduler_started != 0U) {
        xPortSysTickHandler();
    }
}

static void router_task(void *argument)
{
    (void)argument;
    (void)Router_SendHello(NULL);
    for (;;) {
        power_stage_off();
        Router_Service(8U);
        Router_Maintenance();
        vTaskDelay(pdMS_TO_TICKS(5U));
    }
}

static void monitor_task(void *argument)
{
    TickType_t last_report = xTaskGetTickCount();
    uint8_t previous_button =
        (HAL_GPIO_ReadPin(GPIOC, GPIO_PIN_13) == GPIO_PIN_SET) ? 1U : 0U;
    uint32_t rises = 0U;
    uint32_t falls = 0U;

    (void)argument;
    for (;;) {
        RouterStatus_t status;
        RouterNodeInfo_t node;
        uint8_t found = 0U;
        uint8_t button =
            (HAL_GPIO_ReadPin(GPIOC, GPIO_PIN_13) == GPIO_PIN_SET) ? 1U : 0U;
        char line[192];

        power_stage_off();
        if (button != previous_button) {
            if (button != 0U) {
                rises++;
            } else {
                falls++;
            }
            previous_button = button;
        }
        if ((xTaskGetTickCount() - last_report) < pdMS_TO_TICKS(2000U)) {
            vTaskDelay(pdMS_TO_TICKS(20U));
            continue;
        }

        Router_GetStatus(&status);
        for (uint32_t i = 0U; i < Router_GetNodeCount(); ++i) {
            if (Router_GetNode(i, &node) != 0U && node.node_id == 2U &&
                node.port == ROUTER_PORT_ESP32) {
                found = 1U;
                break;
            }
        }
        (void)snprintf(line, sizeof(line),
                       "REAL-STACK SD=0 PWM=OFF ESP_NODE=%u DISC_RX=%lu DISC_TX=%lu PARSE_ERR=%lu PC13=%u RISE=%lu FALL=%lu\r\n",
                       (unsigned)found,
                       (unsigned long)status.discovery_rx,
                       (unsigned long)status.discovery_tx,
                       (unsigned long)status.parse_errors,
                       (unsigned)button,
                       (unsigned long)rises,
                       (unsigned long)falls);
        console_write(line);
        last_report = xTaskGetTickCount();
        vTaskDelay(pdMS_TO_TICKS(20U));
    }
}

int main(void)
{
    SCB->VTOR = 0x20000000U;
    HAL_Init();
    power_stage_off();
    button_input_init();
    memset(&console_uart, 0, sizeof(console_uart));
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
    if (HAL_UART_Init(&console_uart) != HAL_OK) {
        for (;;) { power_stage_off(); }
    }
    console_write("REAL ESP STACK DIAG: SD=0 PWM/FOC OFF, RAM ONLY\r\n");
    if (Router_Init(1U) == 0U || EspLink_Init() == 0U) {
        console_write("REAL ESP STACK INIT FAILED\r\n");
        for (;;) { power_stage_off(); }
    }
    Router_RegisterPortTx(ROUTER_PORT_ESP32, EspLink_RouterTx);
    if (xTaskCreate(EspLink_Task, "EspLink", 512U, NULL, 2U, NULL) != pdPASS ||
        xTaskCreate(router_task, "Router", 512U, NULL, 2U, NULL) != pdPASS ||
        xTaskCreate(monitor_task, "Monitor", 384U, NULL, 1U, NULL) != pdPASS) {
        console_write("REAL ESP STACK TASK CREATE FAILED\r\n");
        for (;;) { power_stage_off(); }
    }
    scheduler_started = 1U;
    vTaskStartScheduler();
    for (;;) { power_stage_off(); }
}
