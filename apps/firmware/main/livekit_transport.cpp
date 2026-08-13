#include "livekit_transport.h"

#include <algorithm>
#include <array>
#include <cstring>

#include "cJSON.h"
#include "esp_crt_bundle.h"
#include "esp_heap_caps.h"
#include "esp_http_client.h"
#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "livekit.h"

#include "display.h"
#include "media.h"
#include "network.h"
#include "power.h"

namespace {
constexpr char kTag[] = "memora-livekit";
constexpr char kDeviceTopic[] = "device";
constexpr char kDisplayTopic[] = "display";
livekit_room_handle_t s_room = nullptr;

struct TokenResponse {
    std::array<char, 4096> body{};
    std::size_t length = 0;
};

std::array<char, 2048> s_server_url{};
std::array<char, 4096> s_token{};
TokenResponse s_token_response;

esp_err_t on_token_http_event(esp_http_client_event_t* event) {
    if (event == nullptr || event->event_id != HTTP_EVENT_ON_DATA || event->data == nullptr ||
        event->data_len <= 0 || event->user_data == nullptr) {
        return ESP_OK;
    }
    auto* response = static_cast<TokenResponse*>(event->user_data);
    const std::size_t available = response->body.size() - 1 - response->length;
    const std::size_t copy_size = std::min<std::size_t>(available, event->data_len);
    if (copy_size > 0) {
        std::memcpy(response->body.data() + response->length, event->data, copy_size);
        response->length += copy_size;
        response->body[response->length] = '\0';
    }
    return ESP_OK;
}

bool fetch_dashboard_token() {
    if (CONFIG_MEMORA_TOKEN_URL[0] == '\0') {
        return false;
    }

    cJSON* request = cJSON_CreateObject();
    if (request == nullptr) {
        return false;
    }
    cJSON_AddStringToObject(request, "room_name", CONFIG_MEMORA_LIVEKIT_ROOM);
    cJSON_AddStringToObject(request, "identity", CONFIG_MEMORA_LIVEKIT_IDENTITY);
    char* request_body = cJSON_PrintUnformatted(request);
    cJSON_Delete(request);
    if (request_body == nullptr) {
        return false;
    }

    s_token_response = {};
    esp_http_client_config_t config = {};
    config.url = CONFIG_MEMORA_TOKEN_URL;
    config.method = HTTP_METHOD_POST;
    config.timeout_ms = 10000;
    config.crt_bundle_attach = esp_crt_bundle_attach;
    config.event_handler = on_token_http_event;
    config.user_data = &s_token_response;
    esp_http_client_handle_t client = esp_http_client_init(&config);
    if (client == nullptr) {
        cJSON_free(request_body);
        ESP_LOGE(kTag, "token HTTP client init failed");
        return false;
    }

    esp_http_client_set_header(client, "Content-Type", "application/json");
    esp_http_client_set_post_field(client, request_body, std::strlen(request_body));
    const esp_err_t request_result = esp_http_client_perform(client);
    const int status_code = esp_http_client_get_status_code(client);
    esp_http_client_cleanup(client);
    cJSON_free(request_body);
    if (request_result != ESP_OK || status_code != 200) {
        ESP_LOGE(kTag, "token request failed: %s HTTP=%d", esp_err_to_name(request_result),
                 status_code);
        return false;
    }

    cJSON* result = cJSON_Parse(s_token_response.body.data());
    cJSON* server_url = result == nullptr ? nullptr : cJSON_GetObjectItem(result, "server_url");
    cJSON* token = result == nullptr ? nullptr : cJSON_GetObjectItem(result, "token");
    const bool valid = cJSON_IsString(server_url) && cJSON_IsString(token) &&
                       server_url->valuestring[0] != '\0' && token->valuestring[0] != '\0';
    if (valid) {
        s_server_url.fill('\0');
        s_token.fill('\0');
        std::strncpy(s_server_url.data(), server_url->valuestring, s_server_url.size() - 1);
        std::strncpy(s_token.data(), token->valuestring, s_token.size() - 1);
        ESP_LOGI(kTag, "token received for room=%s identity=%s", CONFIG_MEMORA_LIVEKIT_ROOM,
                 CONFIG_MEMORA_LIVEKIT_IDENTITY);
    } else {
        ESP_LOGE(kTag, "token response missing server_url or token");
    }
    cJSON_Delete(result);
    return valid;
}

void on_state_changed(livekit_connection_state_t state, void*) {
    ESP_LOGI(kTag, "room state: %s", livekit_connection_state_str(state));
    if (state == LIVEKIT_CONNECTION_STATE_CONNECTED) {
        ESP_LOGI(kTag, "heap before media pipeline: free=%u largest=%u internal=%u largest_internal=%u",
                 static_cast<unsigned>(esp_get_free_heap_size()),
                 static_cast<unsigned>(heap_caps_get_largest_free_block(MALLOC_CAP_8BIT)),
                 static_cast<unsigned>(heap_caps_get_free_size(MALLOC_CAP_INTERNAL)),
                 static_cast<unsigned>(heap_caps_get_largest_free_block(MALLOC_CAP_INTERNAL)));
    }
    if (s_room != nullptr) {
        const auto reason = livekit_room_get_failure_reason(s_room);
        if (reason != LIVEKIT_FAILURE_REASON_NONE) {
            ESP_LOGW(kTag, "room failure: %s", livekit_failure_reason_str(reason));
        }
    }
}

void on_data_received(const livekit_data_received_t* data, void*) {
    if (data == nullptr || data->topic == nullptr || data->payload.bytes == nullptr) {
        return;
    }
    if (std::strcmp(data->topic, kDisplayTopic) == 0) {
        memora::display::show(data->payload.bytes, data->payload.size);
    }
}

void telemetry_task(void*) {
    for (;;) {
        memora::livekit::publish_telemetry(false);
        vTaskDelay(pdMS_TO_TICKS(30000));
    }
}
}  // namespace

namespace memora::livekit {

bool init() {
    const auto result = ::livekit_system_init();
    if (result != LIVEKIT_ERR_NONE) {
        ESP_LOGE(kTag, "LiveKit system init failed: %d", result);
        return false;
    }
    return true;
}

bool connect() {
    if (!network::connected()) {
        ESP_LOGE(kTag, "cannot connect before Wi-Fi");
        return false;
    }
    bool token_ready = fetch_dashboard_token();
    if (!token_ready && CONFIG_MEMORA_LIVEKIT_TOKEN[0] != '\0' &&
        CONFIG_MEMORA_LIVEKIT_SERVER_URL[0] != '\0') {
        std::strncpy(s_server_url.data(), CONFIG_MEMORA_LIVEKIT_SERVER_URL, s_server_url.size() - 1);
        std::strncpy(s_token.data(), CONFIG_MEMORA_LIVEKIT_TOKEN, s_token.size() - 1);
        token_ready = true;
        ESP_LOGW(kTag, "using fallback pre-generated LiveKit token");
    }
    if (!token_ready) {
        ESP_LOGE(kTag, "unable to obtain LiveKit token; check MEMORA_TOKEN_URL");
        return false;
    }

    livekit_room_options_t options = {};
    options.publish.kind = LIVEKIT_MEDIA_TYPE_AUDIO;
    options.publish.audio_encode.codec = LIVEKIT_AUDIO_CODEC_OPUS;
    options.publish.audio_encode.sample_rate = 16000;
    options.publish.audio_encode.channel_count = 1;
    options.publish.capturer = memora::media::capture();
    options.on_state_changed = &on_state_changed;
    options.on_data_received = &on_data_received;
    if (options.publish.capturer == nullptr) {
        ESP_LOGE(kTag, "media capture is not initialized");
        return false;
    }
    if (::livekit_room_create(&s_room, &options) != LIVEKIT_ERR_NONE) {
        ESP_LOGE(kTag, "room create failed");
        return false;
    }
    const auto result = ::livekit_room_connect(s_room, s_server_url.data(), s_token.data());
    if (result != LIVEKIT_ERR_NONE) {
        ESP_LOGE(kTag, "room connect failed: %d", result);
        return false;
    }
    ESP_LOGI(kTag, "connecting as %s to room %s with mic=%uHz mono (video via JPEG bridge)",
             CONFIG_MEMORA_LIVEKIT_IDENTITY, CONFIG_MEMORA_LIVEKIT_ROOM,
             options.publish.audio_encode.sample_rate);
    xTaskCreate(telemetry_task, "telemetry", 3072, nullptr, 4, nullptr);
    return true;
}

void publish_telemetry(bool button_pressed) {
    if (s_room == nullptr || !network::connected()) {
        return;
    }

    cJSON* object = cJSON_CreateObject();
    if (object == nullptr) {
        return;
    }
    const float battery = power::battery_level();
    if (battery >= 0.0f) {
        cJSON_AddNumberToObject(object, "battery_level", battery);
    } else {
        cJSON_AddNullToObject(object, "battery_level");
    }
    cJSON_AddBoolToObject(object, "wifi_connected", network::connected());
    cJSON_AddBoolToObject(object, "button_pressed", button_pressed);

    char* json = cJSON_PrintUnformatted(object);
    if (json != nullptr) {
        livekit_data_payload_t payload = {
            .bytes = reinterpret_cast<uint8_t*>(json),
            .size = std::strlen(json),
        };
        livekit_data_publish_options_t options = {
            .payload = &payload,
            .topic = const_cast<char*>(kDeviceTopic),
            .lossy = false,
            .destination_identities = nullptr,
            .destination_identities_count = 0,
        };
        const auto result = ::livekit_room_publish_data(s_room, &options);
        if (result != LIVEKIT_ERR_NONE) {
            ESP_LOGW(kTag, "telemetry publish failed: %d", result);
        }
        cJSON_free(json);
    }
    cJSON_Delete(object);
}

}  // namespace memora::livekit
