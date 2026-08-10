#include "display.h"

#include <algorithm>
#include <cstring>

#include "driver/i2c_master.h"
#include "esp_log.h"

#include "hardware.h"

namespace {
constexpr char kTag[] = "memora-display";
i2c_master_bus_handle_t s_bus = nullptr;
i2c_master_dev_handle_t s_oled = nullptr;

void write_command(uint8_t command) {
    if (s_oled == nullptr) {
        return;
    }
    const uint8_t packet[] = {0x00, command};
    i2c_master_transmit(s_oled, packet, sizeof(packet), 100);
}
}  // namespace

namespace memora::display {

void init() {
    i2c_master_bus_config_t bus_config = {};
    bus_config.i2c_port = I2C_NUM_0;
    bus_config.sda_io_num = hardware::kOledSda;
    bus_config.scl_io_num = hardware::kOledScl;
    bus_config.clk_source = I2C_CLK_SRC_DEFAULT;
    bus_config.glitch_ignore_cnt = 7;
    bus_config.flags.enable_internal_pullup = true;

    esp_err_t err = i2c_new_master_bus(&bus_config, &s_bus);
    if (err != ESP_OK) {
        ESP_LOGE(kTag, "OLED I2C bus init failed: %s", esp_err_to_name(err));
        return;
    }

    i2c_device_config_t device_config = {};
    device_config.dev_addr_length = I2C_ADDR_BIT_LEN_7;
    device_config.device_address = hardware::kOledAddress;
    device_config.scl_speed_hz = 400000;
    err = i2c_master_bus_add_device(s_bus, &device_config, &s_oled);
    if (err != ESP_OK) {
        ESP_LOGE(kTag, "OLED device init failed: %s", esp_err_to_name(err));
        return;
    }

    // SSD1306-compatible controller initialization. Text rasterization will be
    // added once the exact OLED controller/resolution is confirmed.
    constexpr uint8_t commands[] = {0xAE, 0xD5, 0x80, 0xA8, 0x3F, 0xD3, 0x00,
                                    0x40, 0x8D, 0x14, 0x20, 0x00, 0xA1, 0xC8,
                                    0xDA, 0x12, 0x81, 0x7F, 0xD9, 0xF1, 0xDB,
                                    0x40, 0xA4, 0xA6, 0xAF};
    for (uint8_t command : commands) {
        write_command(command);
    }
    ESP_LOGI(kTag, "OLED bus ready on SDA=%d SCL=%d", hardware::kOledSda,
             hardware::kOledScl);
}

void show(const uint8_t* payload, std::size_t length) {
    if (payload == nullptr || length == 0) {
        return;
    }
    // Keep the transport contract intact even before the font renderer lands.
    // This gives useful serial output during backend integration testing.
    const std::size_t preview_length = std::min<std::size_t>(length, 160);
    ESP_LOGI(kTag, "display payload (%u bytes): %.*s", static_cast<unsigned>(length),
             static_cast<int>(preview_length), reinterpret_cast<const char*>(payload));
}

void show(const char* text) {
    if (text == nullptr) {
        return;
    }
    show(reinterpret_cast<const uint8_t*>(text), std::strlen(text));
}

}  // namespace memora::display
