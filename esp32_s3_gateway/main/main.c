#include <stdio.h>
#include <string.h>

#include "driver/uart.h"
#include "esp_check.h"
#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

#include "router_frame.h"
#include "gateway.h"
#if CONFIG_GATEWAY_ROUTER_ENABLE
#include "router.h"
#include "router_network.h"
#include "router_tcp.h"
#endif

#define LINK_UART UART_NUM_1
#define LOCAL_NODE_ID 2U
#define STM32_NODE_ID 1U
#define ROUTER_TYPE_PROTOCOL 1U
#define ROUTER_TYPE_DISCOVERY 3U
#define ROUTER_BROADCAST 65535U

static const char *TAG = "stm32_link";
#if !CONFIG_GATEWAY_ROUTER_ENABLE
static uint16_t next_seq = 1U;
#endif

static void uart_internal_loopback_self_test(void)
{
    const router_frame_t expected = {
        .src = LOCAL_NODE_ID,
        .dst = ROUTER_BROADCAST,
        .type = ROUTER_TYPE_DISCOVERY,
        .seq = 123U,
        .ttl = 8U,
        .length = 5U,
        .payload = "HELLO",
    };
    router_frame_t received;
    char tx[ROUTER_FRAME_MAX_LINE + 2U];
    char rx[ROUTER_FRAME_MAX_LINE + 1U];
    const size_t length = router_frame_format(&expected, tx, sizeof(tx) - 1U);
    size_t count = 0U;
    unsigned skipped = 0U;
    bool in_frame = false;
    bool complete = false;
    bool passed = false;

    if (length == 0U || uart_flush_input(LINK_UART) != ESP_OK ||
        uart_set_loop_back(LINK_UART, true) != ESP_OK) {
        ESP_LOGE(TAG, "UART1 internal loopback setup failed");
        return;
    }

    vTaskDelay(pdMS_TO_TICKS(10));
    (void)uart_flush_input(LINK_UART);
    tx[length] = '\n';
    if (uart_write_bytes(LINK_UART, tx, length + 1U) == (int)(length + 1U) &&
        uart_wait_tx_done(LINK_UART, pdMS_TO_TICKS(1000)) == ESP_OK) {
        for (unsigned attempt = 0U; !complete && attempt < length + 32U; ++attempt) {
            uint8_t byte;
            if (uart_read_bytes(LINK_UART, &byte, 1U, pdMS_TO_TICKS(100)) != 1) {
                continue;
            }
            if (!in_frame) {
                if (byte == '@') {
                    rx[count++] = (char)byte;
                    in_frame = true;
                } else {
                    ++skipped;
                }
            } else if (byte == '\n') {
                complete = true;
            } else if (count < sizeof(rx) - 1U) {
                rx[count++] = (char)byte;
            } else {
                break;
            }
        }
        if (complete && count == length && memcmp(tx, rx, length) == 0) {
            rx[length] = '\0';
            passed = router_frame_parse(rx, &received) &&
                     received.src == expected.src &&
                     received.dst == expected.dst &&
                     received.type == expected.type &&
                     strcmp(received.payload, expected.payload) == 0;
            if (!passed) {
                ESP_LOGE(TAG, "UART1 loopback bytes match but Router parse failed");
            }
        } else if (count == length) {
            for (size_t i = 0U; i < length; ++i) {
                if (tx[i] != rx[i]) {
                    ESP_LOGE(TAG, "UART1 loopback mismatch at %u: TX=0x%02X RX=0x%02X",
                             (unsigned)i, (unsigned char)tx[i], (unsigned char)rx[i]);
                    break;
                }
            }
        }
    }

    (void)uart_set_loop_back(LINK_UART, false);
    (void)uart_flush_input(LINK_UART);
    if (passed) {
        ESP_LOGI(TAG, "UART1 INTERNAL LOOPBACK PASS (%u bytes, skipped=%u, Router frame parsed)",
                 (unsigned)length, skipped);
    } else {
        ESP_LOGE(TAG, "UART1 INTERNAL LOOPBACK FAIL (%u/%u bytes, skipped=%u, complete=%u)",
                 (unsigned)count, (unsigned)length, skipped, (unsigned)complete);
    }
}

static void send_frame(uint16_t destination, uint8_t type, const char *payload)
{
#if CONFIG_GATEWAY_ROUTER_ENABLE
    (void)Router_SendText(destination, type, payload, NULL);
#else
    router_frame_t frame = {0};
    char line[ROUTER_FRAME_MAX_LINE + 2U];
    size_t used;

    frame.src = LOCAL_NODE_ID;
    frame.dst = destination;
    frame.type = type;
    frame.seq = next_seq++;
    frame.ttl = 8U;
    frame.length = (uint16_t)strlen(payload);
    if (frame.length > ROUTER_FRAME_MAX_PAYLOAD) {
        ESP_LOGE(TAG, "payload too long");
        return;
    }
    memcpy(frame.payload, payload, frame.length + 1U);
    used = router_frame_format(&frame, line, sizeof(line) - 2U);
    if (used == 0U) {
        ESP_LOGE(TAG, "frame format failed");
        return;
    }
    line[used++] = '\r';
    line[used++] = '\n';
    const int sent = uart_write_bytes(LINK_UART, line, used);
    if (sent != (int)used) {
        ESP_LOGW(TAG, "UART TX short write: %d/%u", sent, (unsigned)used);
    }
#endif
}

#if CONFIG_GATEWAY_ROUTER_ENABLE
static uint8_t router_uart_tx(const RouterPacket_t *packet)
{
    char line[ROUTER_FRAME_MAX_LINE + 2U];
    size_t count = Router_EncodeAsciiFrame(packet, line, sizeof(line) - 2U);
    if (!count) return 0;
    line[count++] = '\r'; line[count++] = '\n';
    return uart_write_bytes(LINK_UART, line, count) == (int)count ? 1U : 0U;
}
#endif

static void handle_line(const char *line)
{
    router_frame_t frame;
    unsigned request_id;
    char suffix;
    char reply[64];

    if (!router_frame_parse(line, &frame)) {
        ESP_LOGW(TAG, "drop invalid router frame");
        return;
    }
#if CONFIG_GATEWAY_ROUTER_ENABLE
    if (rn_allowed(frame.src, frame.dst, frame.type, frame.ttl, frame.payload)) {
        (void)Router_SubmitAsciiLine(ROUTER_PORT_UART1, line);
        return;
    }
#endif
    if (frame.src != STM32_NODE_ID ||
        (frame.dst != LOCAL_NODE_ID && frame.dst != ROUTER_BROADCAST)) {
        return;
    }
    ESP_LOGI(TAG, "RX src=%u dst=%u type=%u payload=%s",
             (unsigned)frame.src, (unsigned)frame.dst,
             (unsigned)frame.type, frame.payload);

    if (frame.dst == LOCAL_NODE_ID && frame.type == 2U) {
        net_sample_t sample;
        if (net_sample_parse(frame.payload, &sample)) gateway_observe(&sample);
        else gateway_rejected();
        return;
    }
    /* PING remains separate from observations. No motor commands. */
    if (frame.dst == LOCAL_NODE_ID && frame.type == ROUTER_TYPE_PROTOCOL &&
        sscanf(frame.payload, "%u PING %c", &request_id, &suffix) == 1 &&
        request_id <= 65535U) {
        snprintf(reply, sizeof(reply), "%u OK ESP32 PONG", request_id);
        send_frame(frame.src, ROUTER_TYPE_PROTOCOL, reply);
    }
}

void app_main(void)
{
    const uart_config_t uart_config = {
        .baud_rate = CONFIG_STM32_LINK_BAUD,
        .data_bits = UART_DATA_8_BITS,
        .parity = UART_PARITY_DISABLE,
        .stop_bits = UART_STOP_BITS_1,
        .flow_ctrl = UART_HW_FLOWCTRL_DISABLE,
        .source_clk = UART_SCLK_DEFAULT,
    };
    char line[ROUTER_FRAME_MAX_LINE + 1U];
    size_t line_length = 0U;
    bool dropping = false;
#if !CONFIG_GATEWAY_ROUTER_ENABLE
    TickType_t last_hello;
#endif

    ESP_ERROR_CHECK(uart_driver_install(LINK_UART, 1024, 1024, 0, NULL, 0));
    ESP_ERROR_CHECK(uart_param_config(LINK_UART, &uart_config));
    ESP_ERROR_CHECK(uart_set_pin(LINK_UART, CONFIG_STM32_LINK_TX_GPIO,
                                 CONFIG_STM32_LINK_RX_GPIO,
                                 UART_PIN_NO_CHANGE, UART_PIN_NO_CHANGE));
    uart_internal_loopback_self_test();
#if CONFIG_GATEWAY_ROUTER_ENABLE
    ESP_ERROR_CHECK(Router_Init(LOCAL_NODE_ID) ? ESP_OK : ESP_ERR_NO_MEM);
    Router_RegisterPortTx(ROUTER_PORT_UART1, router_uart_tx);
#endif
    gateway_init();
#if CONFIG_GATEWAY_ROUTER_ENABLE
    router_tcp_init();
#endif
    ESP_LOGI(TAG, "ESP32-S3 node %u, UART1 %d baud, TX GPIO%d RX GPIO%d",
             LOCAL_NODE_ID, CONFIG_STM32_LINK_BAUD,
             CONFIG_STM32_LINK_TX_GPIO, CONFIG_STM32_LINK_RX_GPIO);
    ESP_LOGW(TAG, "software only: verify board pins and STM32 link before wiring");

#if !CONFIG_GATEWAY_ROUTER_ENABLE
    last_hello = xTaskGetTickCount();
#endif
    send_frame(ROUTER_BROADCAST, ROUTER_TYPE_DISCOVERY, "HELLO");
    for (;;) {
        uint8_t bytes[64];
        const int count = uart_read_bytes(LINK_UART, bytes, sizeof(bytes),
                                          pdMS_TO_TICKS(20));
        for (int i = 0; i < count; ++i) {
            const uint8_t ch = bytes[i];
            if (ch == '\r' || ch == '\n') {
                if (!dropping && line_length != 0U) {
                    line[line_length] = '\0';
                    handle_line(line);
                }
                line_length = 0U;
                dropping = false;
            } else if (ch >= 0x20U && ch <= 0x7EU && !dropping) {
                if (line_length < ROUTER_FRAME_MAX_LINE) {
                    line[line_length++] = (char)ch;
                } else {
                    dropping = true;
                    line_length = 0U;
                    ESP_LOGW(TAG, "drop overlong UART line");
                }
            }
        }
#if CONFIG_GATEWAY_ROUTER_ENABLE
        router_tcp_service();
        Router_Service(8U);
        Router_Maintenance();
#else
        if ((xTaskGetTickCount() - last_hello) >= pdMS_TO_TICKS(5000)) {
            send_frame(ROUTER_BROADCAST, ROUTER_TYPE_DISCOVERY, "HELLO");
            last_hello = xTaskGetTickCount();
        }
#endif
    }
}
