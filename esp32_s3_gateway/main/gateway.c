#include "gateway.h"
#include "modbus_ro.h"
#include <inttypes.h>
#include <stdio.h>
#include <string.h>
#include <strings.h>
#include <unistd.h>
#include <time.h>
#include "esp_crt_bundle.h"
#include "esp_event.h"
#include "esp_http_client.h"
#include "esp_log.h"
#include "esp_mac.h"
#include "esp_netif.h"
#include "esp_netif_sntp.h"
#include "esp_random.h"
#include "esp_timer.h"
#include "esp_wifi.h"
#include "freertos/FreeRTOS.h"
#include "freertos/event_groups.h"
#include "freertos/queue.h"
#include "freertos/semphr.h"
#include "freertos/task.h"
#include "lwip/sockets.h"
#include "nvs.h"
#include "nvs_flash.h"

#define WIFI_READY BIT0
#define SAMPLE_QUEUE_DEPTH 64U
#define RESULT_QUEUE_DEPTH 16U
typedef struct { net_sample_t sample; char session[17]; } envelope_t;
typedef struct { char ack[40]; bool overflow; } http_reply_t;
static const char *TAG = "gateway";
static QueueHandle_t samples, results;
static SemaphoreHandle_t lock;
static EventGroupHandle_t events;
static mb_observation_t observation;
static uint64_t last_received_ms;
static uint32_t last_device_ms, last_seq;
static bool have_previous;
static char session[17], device[13], url[256], token[129];

bool gateway_network_ready(void)
{ return events && (xEventGroupGetBits(events) & WIFI_READY) != 0; }

static uint64_t now_ms(void) { return (uint64_t)esp_timer_get_time() / 1000U; }
static void new_session(void)
{ snprintf(session, sizeof(session), "%08" PRIX32 "%08" PRIX32, esp_random(), esp_random()); }
static void snapshot(mb_observation_t *s)
{
    xSemaphoreTake(lock, portMAX_DELAY);
    *s = observation;
    uint64_t age = observation.available ? now_ms() - last_received_ms : UINT32_MAX;
    s->age_ms = age > UINT32_MAX ? UINT32_MAX : (uint32_t)age;
    s->queued = (uint32_t)(uxQueueMessagesWaiting(samples) + uxQueueMessagesWaiting(results));
    xSemaphoreGive(lock);
}
void gateway_rejected(void)
{
    if (!lock) return;
    xSemaphoreTake(lock, portMAX_DELAY); observation.rejected++; xSemaphoreGive(lock);
}
void gateway_observe(const net_sample_t *s)
{
    if (!lock || !net_sample_valid(s)) { gateway_rejected(); return; }
    envelope_t e = {.sample = *s};
    xSemaphoreTake(lock, portMAX_DELAY);
    /* Small UART task scheduling reorders do not create a false reboot.
       This is an observation session, not a safety/replay command nonce. */
    if (have_previous && s->seq < last_seq &&
        (int32_t)(s->uptime_ms - last_device_ms) < -250) new_session();
    if (!have_previous || (int32_t)(s->seq - last_seq) > 0 ||
        (int32_t)(s->uptime_ms - last_device_ms) < -250) {
        observation.sample = *s; observation.available = true;
        last_received_ms = now_ms(); last_device_ms = s->uptime_ms; last_seq = s->seq;
        have_previous = true;
    }
    memcpy(e.session, session, sizeof(session));
    QueueHandle_t q = s->kind == NET_KIND_RESULT ? results : samples;
    if (xQueueSend(q, &e, 0) != pdPASS) observation.dropped++;
    xSemaphoreGive(lock);
}

static void wifi_event(void *arg, esp_event_base_t base, int32_t id, void *data)
{
    (void)arg;
    bool ready;
    if (base == IP_EVENT && id == IP_EVENT_STA_GOT_IP) {
        ip_event_got_ip_t *e = data;
        ESP_LOGI(TAG, "Wi-Fi IP " IPSTR " (read-only Modbus TCP :%d)",
                 IP2STR(&e->ip_info.ip), CONFIG_GATEWAY_MODBUS_PORT);
        ready = true;
    } else if (base == WIFI_EVENT && id == WIFI_EVENT_STA_DISCONNECTED) {
        ESP_LOGW(TAG, "Wi-Fi disconnected; reconnect scheduled"); ready = false;
    } else return;
    xSemaphoreTake(lock, portMAX_DELAY); observation.wifi = ready; xSemaphoreGive(lock);
    if (ready) xEventGroupSetBits(events, WIFI_READY);
    else xEventGroupClearBits(events, WIFI_READY);
}

static esp_err_t http_event(esp_http_client_event_t *e)
{
    http_reply_t *r = e->user_data;
    if (e->event_id == HTTP_EVENT_ON_HEADER && e->header_key && e->header_value &&
        strcasecmp(e->header_key, "X-Observation-Ack") == 0) {
        if (strlen(e->header_value) >= sizeof(r->ack) || r->ack[0]) r->overflow = true;
        else {
            strcpy(r->ack, e->header_value);
        }
    }
    return ESP_OK;
}
static bool upload(const envelope_t *e)
{
    const net_sample_t *s = &e->sample;
    char body[768], authorization[144];
    int n = snprintf(body, sizeof(body),
        "{\"v\":1,\"device\":\"%s\",\"session\":\"%s\",\"sample\":{"
        "\"seq\":%" PRIu32 ",\"uptime_ms\":%" PRIu32 ",\"run\":%" PRIu32
        ",\"cycle\":%u,\"stage\":%u,\"outcome\":%u,\"flags\":%u,\"fault\":%u,"
        "\"position_cdeg\":%" PRId32 ",\"speed_drpm\":%" PRId32 ",\"iq_ma\":%" PRId32
        ",\"vbus_mv\":%" PRIu32 ",\"vbus_quality\":%u,\"contact_cdeg\":%" PRId32
        ",\"post_cdeg\":%" PRId32 ",\"kind\":%u}}",
        device, e->session, s->seq, s->uptime_ms, s->run, s->cycle, s->stage,
        s->outcome, s->flags, s->fault, s->position_cdeg, s->speed_drpm,
        s->iq_ma, s->vbus_mv, s->vbus_quality, s->contact_cdeg, s->post_cdeg, s->kind);
    if (n < 0 || n >= (int)sizeof(body)) return false;
    snprintf(authorization, sizeof(authorization), "Bearer %s", token);
    http_reply_t reply = {0};
    esp_http_client_config_t cfg = {
        .url = url, .method = HTTP_METHOD_POST, .timeout_ms = 2500,
        .disable_auto_redirect = true, .crt_bundle_attach = esp_crt_bundle_attach,
        .event_handler = http_event, .user_data = &reply,
    };
    esp_http_client_handle_t client = esp_http_client_init(&cfg);
    if (!client) return false;
    bool ok = esp_http_client_set_header(client, "Authorization", authorization) == ESP_OK &&
              esp_http_client_set_header(client, "Content-Type", "application/json") == ESP_OK &&
              esp_http_client_set_post_field(client, body, n) == ESP_OK &&
              esp_http_client_perform(client) == ESP_OK;
    int status = esp_http_client_get_status_code(client);
    esp_http_client_cleanup(client);
    memset(authorization, 0, sizeof(authorization));
    if (!ok || reply.overflow || (status != 200 && status != 201)) return false;
    char expected[40];
    snprintf(expected, sizeof(expected), "%s:%" PRIu32, e->session, s->seq);
    return strcmp(expected, reply.ack) == 0;
}

static void upload_task(void *arg)
{
    (void)arg;
    envelope_t pending;
    QueueHandle_t selected = NULL;
    uint32_t retry_ms = 1000, reconnect_ms = 1000;
    uint64_t next_try = 0, next_connect = 0, last_report = 0;
    for (;;) {
        uint64_t now = now_ms();
        bool wifi = (xEventGroupGetBits(events) & WIFI_READY) != 0;
        if (!wifi && now >= next_connect) {
            (void)esp_wifi_connect(); next_connect = now + reconnect_ms;
            if (reconnect_ms < 30000) reconnect_ms *= 2;
            if (reconnect_ms > 30000) reconnect_ms = 30000;
        }
        if (wifi) reconnect_ms = 1000;
        if (!selected) {
            if (xQueuePeek(results, &pending, 0) == pdPASS) selected = results;
            else if (xQueuePeek(samples, &pending, 0) == pdPASS) selected = samples;
        }
        /* HTTPS certificate validation needs trustworthy wall-clock time.
           Device uptime and server receipt time are still kept separately. */
        bool time_ready = strncmp(url, "https://", 8) != 0 || time(NULL) > 1704067200;
        if (wifi && time_ready && selected && now >= next_try) {
            bool ok = upload(&pending);
            if (ok) {
                envelope_t discarded;
                (void)xQueueReceive(selected, &discarded, 0);
                selected = NULL; retry_ms = 1000; next_try = 0;
                xSemaphoreTake(lock, portMAX_DELAY); observation.uploaded++; xSemaphoreGive(lock);
            } else {
                xSemaphoreTake(lock, portMAX_DELAY); observation.upload_errors++; xSemaphoreGive(lock);
                next_try = now_ms() + retry_ms;
                retry_ms = retry_ms < 15000 ? retry_ms * 2 : 30000;
            }
        }
        if (now - last_report >= 10000) {
            mb_observation_t state; snapshot(&state);
            ESP_LOGI(TAG, "wifi=%u fresh=%u uploaded=%" PRIu32 " queued=%" PRIu32
                     " dropped=%" PRIu32 " http_fail=%" PRIu32 " rejected=%" PRIu32 " control=LOCKED",
                     state.wifi, state.available && state.age_ms <= 3000, state.uploaded,
                     state.queued, state.dropped, state.upload_errors, state.rejected);
            last_report = now;
        }
        vTaskDelay(pdMS_TO_TICKS(100));
    }
}

static bool read_exact(int fd, uint8_t *out, size_t count)
{
    size_t done = 0;
    uint64_t deadline = now_ms() + 2000U;
    while (done < count) {
        if (now_ms() > deadline) return false;
        int n = recv(fd, out + done, count - done, 0);
        if (n <= 0 || now_ms() > deadline) return false;
        done += (size_t)n;
    }
    return true;
}
static bool write_exact(int fd, const uint8_t *data, size_t count)
{
    size_t done = 0;
    uint64_t deadline = now_ms() + 2000U;
    while (done < count) {
        if (now_ms() > deadline) return false;
        int n = send(fd, data + done, count - done, 0);
        if (n <= 0 || now_ms() > deadline) return false;
        done += (size_t)n;
    }
    return true;
}
static void modbus_task(void *arg)
{
    (void)arg;
    for (;;) {
        (void)xEventGroupWaitBits(events, WIFI_READY, pdFALSE, pdTRUE, portMAX_DELAY);
        int listener = socket(AF_INET, SOCK_STREAM, IPPROTO_IP);
        if (listener < 0) { vTaskDelay(pdMS_TO_TICKS(1000)); continue; }
        int reuse = 1; setsockopt(listener, SOL_SOCKET, SO_REUSEADDR, &reuse, sizeof(reuse));
        struct sockaddr_in addr = {.sin_family = AF_INET, .sin_port = htons(CONFIG_GATEWAY_MODBUS_PORT), .sin_addr.s_addr = htonl(INADDR_ANY)};
        if (bind(listener, (struct sockaddr *)&addr, sizeof(addr)) < 0 || listen(listener, 2) < 0) {
            close(listener); vTaskDelay(pdMS_TO_TICKS(1000)); continue;
        }
        while ((xEventGroupGetBits(events) & WIFI_READY) != 0) {
            struct timeval timeout = {.tv_sec = 1};
            fd_set ready; FD_ZERO(&ready); FD_SET(listener, &ready);
            if (select(listener + 1, &ready, NULL, NULL, &timeout) <= 0) continue;
            int fd = accept(listener, NULL, NULL);
            if (fd < 0) continue;
            timeout.tv_sec = 2;
            setsockopt(fd, SOL_SOCKET, SO_RCVTIMEO, &timeout, sizeof(timeout));
            setsockopt(fd, SOL_SOCKET, SO_SNDTIMEO, &timeout, sizeof(timeout));
            uint64_t deadline = now_ms() + 10000U;
            unsigned requests = 0;
            while (requests++ < 32U && now_ms() < deadline) {
                uint8_t q[260], r[260];
                if (!read_exact(fd, q, 7)) break;
                unsigned length = ((unsigned)q[4] << 8) | q[5];
                if (q[2] || q[3] || length < 2 || length > 254 ||
                    !read_exact(fd, q + 7, length - 1U)) break;
                mb_observation_t state; snapshot(&state);
                size_t n = mb_readonly_reply(q, 6U + length, &state, r, sizeof(r));
                if (!n || !write_exact(fd, r, n)) break;
            }
            close(fd);
        }
        close(listener);
    }
}

static bool get_text(nvs_handle_t h, const char *key, char *out, size_t capacity)
{ size_t n = capacity; return nvs_get_str(h, key, out, &n) == ESP_OK; }
static bool valid_token(const char *value)
{
    size_t length = strlen(value);
    if (length < 24U || length > 128U) return false;
    for (size_t i = 0; i < length; ++i)
        if ((unsigned char)value[i] < 33U || (unsigned char)value[i] > 126U) return false;
    return true;
}
void gateway_init(void)
{
    lock = xSemaphoreCreateMutex(); samples = xQueueCreate(SAMPLE_QUEUE_DEPTH, sizeof(envelope_t));
    results = xQueueCreate(RESULT_QUEUE_DEPTH, sizeof(envelope_t)); events = xEventGroupCreate();
    if (!lock || !samples || !results || !events) {
        ESP_LOGE(TAG, "Gateway resources unavailable; network disabled"); lock = NULL; return;
    }
    new_session();
    uint8_t mac[6]; ESP_ERROR_CHECK(esp_read_mac(mac, ESP_MAC_WIFI_STA));
    snprintf(device, sizeof(device), "%02X%02X%02X%02X%02X%02X", mac[0], mac[1], mac[2], mac[3], mac[4], mac[5]);
    esp_err_t err = nvs_flash_init();
    if (err != ESP_OK) { ESP_LOGE(TAG, "NVS unavailable (%s); NOT erased", esp_err_to_name(err)); return; }
    nvs_handle_t h;
    if (nvs_open("gateway", NVS_READONLY, &h) != ESP_OK) {
        ESP_LOGW(TAG, "No network provisioning; UART still active, control locked"); return;
    }
    wifi_config_t config = {0};
    char ssid[33], password[65]; uint8_t allow_http = 0;
    bool valid = get_text(h, "ssid", ssid, sizeof(ssid)) && get_text(h, "pass", password, sizeof(password)) &&
                 get_text(h, "url", url, sizeof(url)) && get_text(h, "token", token, sizeof(token));
    (void)nvs_get_u8(h, "allow_http", &allow_http); nvs_close(h);
    bool https = strncmp(url, "https://", 8) == 0;
    bool local_http = allow_http == 1 && strncmp(url, "http://", 7) == 0;
    if (!valid || !ssid[0] || strlen(password) < 8 || strlen(password) > 63 ||
        !valid_token(token) || (!https && !local_http)) {
        ESP_LOGE(TAG, "Invalid network provisioning; credentials not logged"); memset(password, 0, sizeof(password)); return;
    }
    memcpy(config.sta.ssid, ssid, strlen(ssid)); memcpy(config.sta.password, password, strlen(password));
    config.sta.threshold.authmode = WIFI_AUTH_WPA2_PSK;
    config.sta.sae_pwe_h2e = WPA3_SAE_PWE_BOTH;
    memset(password, 0, sizeof(password));
    ESP_ERROR_CHECK(esp_netif_init()); ESP_ERROR_CHECK(esp_event_loop_create_default());
    (void)esp_netif_create_default_wifi_sta();
    wifi_init_config_t init = WIFI_INIT_CONFIG_DEFAULT();
    ESP_ERROR_CHECK(esp_wifi_init(&init));
    ESP_ERROR_CHECK(esp_wifi_set_storage(WIFI_STORAGE_RAM));
    ESP_ERROR_CHECK(esp_event_handler_register(WIFI_EVENT, WIFI_EVENT_STA_DISCONNECTED, wifi_event, NULL));
    ESP_ERROR_CHECK(esp_event_handler_register(IP_EVENT, IP_EVENT_STA_GOT_IP, wifi_event, NULL));
    ESP_ERROR_CHECK(esp_wifi_set_mode(WIFI_MODE_STA)); ESP_ERROR_CHECK(esp_wifi_set_config(WIFI_IF_STA, &config));
    ESP_ERROR_CHECK(esp_wifi_start());
    memset(&config, 0, sizeof(config));
    if (https) {
        esp_sntp_config_t time_config = ESP_NETIF_SNTP_DEFAULT_CONFIG("pool.ntp.org");
        ESP_ERROR_CHECK(esp_netif_sntp_init(&time_config));
    } else ESP_LOGW(TAG, "Explicit plaintext LAN demo; not an Internet deployment");
    if (xTaskCreate(upload_task, "NetUpload", 6144, NULL, 2, NULL) != pdPASS ||
        xTaskCreate(modbus_task, "ModbusRO", 4096, NULL, 2, NULL) != pdPASS)
        ESP_LOGE(TAG, "Network worker creation failed; control remains locked");
}
