#include "livekit_transport.h"

#include <cstring>

#include "cJSON.h"
#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "livekit.h"

#include "display.h"
#include "network.h"
#include "power.h"

namespace {
constexpr char kTag[] = "memora-livekit";
constexpr char kDeviceTopic[] = "device";
constexpr char kDisplayTopic[] = "display";
livekit_room_handle_t s_room = nullptr;

void on_state_changed(livekit_connection_state_t state, void*) {
    ESP_LOGI(kTag, "room state: %s", livekit_connection_state_str(state));
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
    if (CONFIG_MEMORA_LIVEKIT_TOKEN[0] == '\0' || CONFIG_MEMORA_LIVEKIT_SERVER_URL[0] == '\0') {
        ESP_LOGE(kTag, "LiveKit URL/token not configured; use idf.py menuconfig");
        return false;
    }

    livekit_room_options_t options = {};
    options.on_state_changed = &on_state_changed;
    options.on_data_received = &on_data_received;
    if (::livekit_room_create(&s_room, &options) != LIVEKIT_ERR_NONE) {
        ESP_LOGE(kTag, "room create failed");
        return false;
    }
    const auto result = ::livekit_room_connect(s_room, CONFIG_MEMORA_LIVEKIT_SERVER_URL,
                                                CONFIG_MEMORA_LIVEKIT_TOKEN);
    if (result != LIVEKIT_ERR_NONE) {
        ESP_LOGE(kTag, "room connect failed: %d", result);
        return false;
    }
    ESP_LOGI(kTag, "connecting as %s to room %s", CONFIG_MEMORA_LIVEKIT_IDENTITY,
             CONFIG_MEMORA_LIVEKIT_ROOM);
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
