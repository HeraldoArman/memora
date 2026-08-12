#include "button.h"

#include "driver/gpio.h"
#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

#include "hardware.h"

namespace {
constexpr char kTag[] = "memora-button";
memora::button::PressCallback s_callback = nullptr;

void task(void*) {
    bool previous = true;
    for (;;) {
        const bool pressed = gpio_get_level(memora::hardware::kButton) == 0;
        if (pressed && !previous && s_callback != nullptr) {
            s_callback();
        }
        previous = pressed;
        vTaskDelay(pdMS_TO_TICKS(20));
    }
}
}  // namespace

namespace memora::button {

void init(PressCallback callback) {
    s_callback = callback;
    gpio_config_t config = {};
    config.pin_bit_mask = 1ULL << hardware::kButton;
    config.mode = GPIO_MODE_INPUT;
    config.pull_up_en = GPIO_PULLUP_ENABLE;
    config.pull_down_en = GPIO_PULLDOWN_DISABLE;
    config.intr_type = GPIO_INTR_DISABLE;
    ESP_ERROR_CHECK(gpio_config(&config));
    xTaskCreate(task, "button", 2048, nullptr, 5, nullptr);
    ESP_LOGI(kTag, "button ready on GPIO%d (active low)", hardware::kButton);
}

}  // namespace memora::button
