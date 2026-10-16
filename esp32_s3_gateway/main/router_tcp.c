#include "router_tcp.h"
#include "router.h"
#include "router_network.h"
#include "gateway.h"
#include <string.h>
#include <unistd.h>
#include <fcntl.h>
#include "esp_log.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"
#include "freertos/task.h"
#include "lwip/sockets.h"

typedef struct { uint32_t generation; uint16_t length; char bytes[RN_MAX_LINE + 2U]; } tcp_tx_t;
static QueueHandle_t tx_queue;
static portMUX_TYPE state_mux = portMUX_INITIALIZER_UNLOCKED;
static uint32_t generation;
static bool connected, changed, route_ready;
static const char *TAG = "router_tcp";
static int64_t now_ms(void) { return esp_timer_get_time() / 1000; }

static void link_state(bool up)
{
    portENTER_CRITICAL(&state_mux);
    connected = up; changed = true; route_ready = false; ++generation;
    portEXIT_CRITICAL(&state_mux);
}
static uint8_t transmit(const RouterPacket_t *packet)
{
    tcp_tx_t tx = {0};
    if (!rn_allowed(packet->src, packet->dst, packet->type, packet->ttl, packet->payload)) return 0;
    portENTER_CRITICAL(&state_mux);
    bool up = connected; tx.generation = generation;
    portEXIT_CRITICAL(&state_mux);
    if (!up) return 0;
    size_t n = Router_EncodeAsciiFrame(packet, tx.bytes, sizeof(tx.bytes) - 2U);
    if (!n) return 0;
    tx.bytes[n++] = '\r'; tx.bytes[n++] = '\n'; tx.length = (uint16_t)n;
    return xQueueSend(tx_queue, &tx, 0) == pdPASS ? 1U : 0U;
}
static void incoming(void *context, const char *line)
{
    (void)context;
    portENTER_CRITICAL(&state_mux);
    bool ready = connected && route_ready;
    portEXIT_CRITICAL(&state_mux);
    if (!ready) return;
    rn_frame_t frame;
    /* IDs 1/2 belong to the physically attached MCU/ESP. Do not accept their
     * impersonation from TCP. This is a LAN policy, NOT authentication. */
    if (rn_parse(line, &frame) && frame.src != 1U && frame.src != 2U &&
        rn_allowed(frame.src, frame.dst, frame.type, frame.ttl, frame.payload))
        (void)Router_SubmitAsciiLine(ROUTER_PORT_SOCKET, line);
}
static bool send_all(int fd, const tcp_tx_t *tx)
{
    size_t offset = 0;
    int64_t deadline = now_ms() + 500;
    while (offset < tx->length && now_ms() < deadline) {
        fd_set write_set; FD_ZERO(&write_set); FD_SET(fd, &write_set);
        struct timeval timeout = {.tv_sec=0, .tv_usec=100000};
        if (select(fd + 1, NULL, &write_set, NULL, &timeout) <= 0) continue;
        int n = send(fd, tx->bytes + offset, tx->length - offset, 0);
        if (n <= 0) return false;
        offset += (size_t)n;
    }
    return offset == tx->length;
}
static void worker(void *argument)
{
    (void)argument;
    for (;;) {
        if (!gateway_network_ready()) { vTaskDelay(pdMS_TO_TICKS(250)); continue; }
        int listener = socket(AF_INET, SOCK_STREAM, IPPROTO_IP);
        if (listener < 0) { vTaskDelay(pdMS_TO_TICKS(1000)); continue; }
        int reuse = 1;
        setsockopt(listener, SOL_SOCKET, SO_REUSEADDR, &reuse, sizeof(reuse));
        struct sockaddr_in address = {.sin_family=AF_INET,
            .sin_port=htons(CONFIG_GATEWAY_ROUTER_PORT), .sin_addr.s_addr=htonl(INADDR_ANY)};
        if (bind(listener, (struct sockaddr *)&address, sizeof(address)) < 0 || listen(listener, 1) < 0) {
            close(listener); vTaskDelay(pdMS_TO_TICKS(1000)); continue;
        }
        int peer = -1;
        uint32_t peer_generation = 0;
        rn_stream_t stream = {0};
        int64_t last_rx = now_ms(), window = last_rx;
        unsigned bytes_in_window = 0;
        while (gateway_network_ready()) {
            fd_set reads; FD_ZERO(&reads); FD_SET(listener, &reads);
            int maximum = listener;
            if (peer >= 0) { FD_SET(peer, &reads); if (peer > maximum) maximum = peer; }
            struct timeval timeout = {.tv_sec=0, .tv_usec=20000};
            int ready = select(maximum + 1, &reads, NULL, NULL, &timeout);
            if (ready < 0) break;
            if (ready > 0 && FD_ISSET(listener, &reads)) {
                int accepted = accept(listener, NULL, NULL);
                if (accepted >= 0) {
                    if (peer >= 0) close(accepted);
                    else {
                        peer = accepted;
                        fcntl(peer, F_SETFL, O_NONBLOCK);
                        stream = (rn_stream_t){0};
                        last_rx = window = now_ms(); bytes_in_window = 0;
                        link_state(true);
                        portENTER_CRITICAL(&state_mux); peer_generation = generation; portEXIT_CRITICAL(&state_mux);
                        ESP_LOGI(TAG, "read-only peer connected; control/Flash closed");
                        /* Newly accepted fd was not in this select snapshot. */
                        FD_CLR(peer, &reads);
                    }
                }
            }
            bool failed = false;
            if (peer >= 0 && ready > 0 && FD_ISSET(peer, &reads)) {
                uint8_t bytes[256];
                int n = recv(peer, bytes, sizeof(bytes), 0);
                if (n <= 0) failed = true;
                else {
                    last_rx = now_ms();
                    if (last_rx - window >= 1000) { window = last_rx; bytes_in_window = 0; }
                    bytes_in_window += (unsigned)n;
                    if (bytes_in_window > 4096U) failed = true;
                    else rn_stream_feed(&stream, bytes, (size_t)n, incoming, NULL);
                }
            }
            tcp_tx_t tx;
            if (xQueueReceive(tx_queue, &tx, 0) == pdPASS && peer >= 0 &&
                tx.generation == peer_generation && !failed) failed = !send_all(peer, &tx);
            if (peer >= 0 && (failed || now_ms() - last_rx > 16000)) {
                close(peer); peer = -1; link_state(false);
            }
        }
        if (peer >= 0) { close(peer); link_state(false); }
        close(listener);
        vTaskDelay(pdMS_TO_TICKS(250));
    }
}
void router_tcp_init(void)
{
    tx_queue = xQueueCreate(8, sizeof(tcp_tx_t));
    if (!tx_queue) return;
    if (xTaskCreate(worker, "RouterTCP", 4096, NULL, 1, NULL) != pdPASS) {
        vQueueDelete(tx_queue); tx_queue = NULL; return;
    }
    Router_RegisterPortTx(ROUTER_PORT_SOCKET, transmit);
}
void router_tcp_service(void)
{
    portENTER_CRITICAL(&state_mux);
    bool update = changed; changed = false;
    bool up = connected;
    uint32_t current_generation = generation;
    portEXIT_CRITICAL(&state_mux);
    if (update) {
        Router_ForgetPort(ROUTER_PORT_SOCKET);
        portENTER_CRITICAL(&state_mux);
        route_ready = up && connected && generation == current_generation;
        bool ready = route_ready;
        portEXIT_CRITICAL(&state_mux);
        if (ready) (void)Router_SendHello(NULL);
    }
}
