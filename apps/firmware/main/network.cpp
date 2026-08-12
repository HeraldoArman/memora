#include "network.h"

#include <cstring>

#include "esp_event.h"
#include "esp_log.h"
#include "esp_netif.h"
#include "esp_wifi.h"
#include "freertos/FreeRTOS.h"
#include "freertos/event_groups.h"

namespace {
constexpr char kTag[] = "memora-network";
constexpr EventBits_t kConnectedBit = BIT0;
constexpr EventBits_t kFailedBit = BIT1;
EventGroupHandle_t s_events = nullptr;
int s_retries = 0;

void on_event(void*, esp_event_base_t base, int32_t id, void*) {
    if (base == WIFI_EVENT && id == WIFI_EVENT_STA_START) {
        esp_wifi_connect();
    } else if (base == WIFI_EVENT && id == WIFI_EVENT_STA_DISCONNECTED) {
        if (s_retries++ < 5) {
            esp_wifi_connect();
        } else {
            xEventGroupSetBits(s_events, kFailedBit);
        }
    } else if (base == IP_EVENT && id == IP_EVENT_STA_GOT_IP) {
        s_retries = 0;
        xEventGroupSetBits(s_events, kConnectedBit);
    }
}
}  // namespace

namespace memora::network {

bool connect() {
    if (CONFIG_MEMORA_WIFI_SSID[0] == '\0') {
        ESP_LOGE(kTag, "Wi-Fi SSID is empty; configure it with idf.py menuconfig");
        return false;
    }

    s_events = xEventGroupCreate();
    ESP_ERROR_CHECK(esp_netif_init());
    ESP_ERROR_CHECK(esp_event_loop_create_default());
    esp_netif_create_default_wifi_sta();

    wifi_init_config_t init_config = WIFI_INIT_CONFIG_DEFAULT();
    ESP_ERROR_CHECK(esp_wifi_init(&init_config));
    ESP_ERROR_CHECK(esp_event_handler_register(WIFI_EVENT, ESP_EVENT_ANY_ID, &on_event,
                                                nullptr));
    ESP_ERROR_CHECK(esp_event_handler_register(IP_EVENT, IP_EVENT_STA_GOT_IP, &on_event,
                                                nullptr));

    wifi_config_t wifi_config = {};
    std::strncpy(reinterpret_cast<char*>(wifi_config.sta.ssid), CONFIG_MEMORA_WIFI_SSID,
                 sizeof(wifi_config.sta.ssid));
    std::strncpy(reinterpret_cast<char*>(wifi_config.sta.password), CONFIG_MEMORA_WIFI_PASSWORD,
                 sizeof(wifi_config.sta.password));
    wifi_config.sta.threshold.authmode = WIFI_AUTH_WPA2_PSK;
    ESP_ERROR_CHECK(esp_wifi_set_mode(WIFI_MODE_STA));
    ESP_ERROR_CHECK(esp_wifi_set_config(WIFI_IF_STA, &wifi_config));
    ESP_ERROR_CHECK(esp_wifi_start());

    const EventBits_t bits = xEventGroupWaitBits(s_events, kConnectedBit | kFailedBit,
                                                  pdFALSE, pdFALSE, pdMS_TO_TICKS(15000));
    if ((bits & kConnectedBit) == 0) {
        ESP_LOGE(kTag, "Wi-Fi connection failed");
        return false;
    }
    ESP_LOGI(kTag, "Wi-Fi connected");
    return true;
}

bool connected() {
    return s_events != nullptr && (xEventGroupGetBits(s_events) & kConnectedBit) != 0;
}

}  // namespace memora::network
