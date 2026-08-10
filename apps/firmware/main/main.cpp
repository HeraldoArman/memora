#include "esp_log.h"
#include "nvs_flash.h"

#include "button.h"
#include "display.h"
#include "livekit_transport.h"
#include "network.h"
#include "power.h"

namespace {
constexpr char kTag[] = "memora";

void on_button_pressed() {
    ESP_LOGI(kTag, "button pressed");
    memora::livekit::publish_telemetry(true);
}
}  // namespace

extern "C" void app_main() {
    esp_err_t nvs_result = nvs_flash_init();
    if (nvs_result == ESP_ERR_NVS_NO_FREE_PAGES || nvs_result == ESP_ERR_NVS_NEW_VERSION_FOUND) {
        ESP_ERROR_CHECK(nvs_flash_erase());
        nvs_result = nvs_flash_init();
    }
    ESP_ERROR_CHECK(nvs_result);

    ESP_LOGI(kTag, "Memora firmware booting");
    memora::display::init();
    memora::power::init();
    memora::button::init(&on_button_pressed);

    if (!memora::network::connect()) {
        memora::display::show("WiFi gagal");
        return;
    }
    if (!memora::livekit::init() || !memora::livekit::connect()) {
        memora::display::show("LiveKit gagal");
        return;
    }

    memora::livekit::publish_telemetry(false);
    memora::display::show("Memora siap");
}
