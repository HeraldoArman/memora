#include "power.h"

#include "esp_log.h"

namespace {
constexpr char kTag[] = "memora-power";
}

namespace memora::power {

void init() {
    // Battery ADC wiring was not provided. Keep telemetry authoritative by
    // reporting an unknown level rather than inventing a percentage.
    ESP_LOGI(kTag, "power manager ready; battery ADC not configured");
}

float battery_level() { return -1.0f; }

}  // namespace memora::power
