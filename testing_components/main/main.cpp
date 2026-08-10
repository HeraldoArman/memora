#include <algorithm>
#include <array>
#include <cstddef>
#include <cstdint>

#include "driver/i2c_master.h"
#include "esp_camera.h"
#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

#include "hardware.h"

namespace {
constexpr char kTag[] = "component-check";
constexpr int kOledWidth = 128;
constexpr int kOledHeight = 64;
constexpr std::size_t kOledBufferSize = kOledWidth * kOledHeight / 8;

i2c_master_bus_handle_t s_i2c_bus = nullptr;
i2c_master_dev_handle_t s_oled = nullptr;

esp_err_t oled_command(uint8_t command) {
    if (s_oled == nullptr) {
        return ESP_ERR_INVALID_STATE;
    }
    const uint8_t packet[] = {0x00, command};
    return i2c_master_transmit(s_oled, packet, sizeof(packet), 100);
}

esp_err_t oled_data(const uint8_t* data, std::size_t length) {
    if (s_oled == nullptr || data == nullptr) {
        return ESP_ERR_INVALID_ARG;
    }

    // Keep I2C transactions small enough for common SSD1306 breakout boards.
    std::array<uint8_t, 17> packet{};
    packet[0] = 0x40;
    while (length > 0) {
        const std::size_t chunk = length < packet.size() - 1 ? length : packet.size() - 1;
        std::copy(data, data + chunk, packet.begin() + 1);
        esp_err_t err = i2c_master_transmit(s_oled, packet.data(), chunk + 1, 100);
        if (err != ESP_OK) {
            return err;
        }
        data += chunk;
        length -= chunk;
    }
    return ESP_OK;
}

void oled_set_page(uint8_t page) {
    oled_command(0xB0 | page);
    oled_command(0x00);
    oled_command(0x10);
}

void oled_pattern(bool inverted) {
    std::array<uint8_t, kOledBufferSize> buffer{};
    for (int page = 0; page < kOledHeight / 8; ++page) {
        for (int x = 0; x < kOledWidth; ++x) {
            const bool border = page == 0 || page == 7 || x == 0 || x == kOledWidth - 1;
            const bool stripes = ((x / 8) + page) % 2 == 0;
            const bool lit = inverted ? !(border || stripes) : (border || stripes);
            if (lit) {
                buffer[page * kOledWidth + x] = 0xFF;
            }
        }
    }

    for (uint8_t page = 0; page < kOledHeight / 8; ++page) {
        oled_set_page(page);
        oled_data(buffer.data() + page * kOledWidth, kOledWidth);
    }
}

bool oled_init() {
    i2c_master_bus_config_t bus_config = {};
    bus_config.i2c_port = I2C_NUM_0;
    bus_config.sda_io_num = test_hardware::kOledSda;
    bus_config.scl_io_num = test_hardware::kOledScl;
    bus_config.clk_source = I2C_CLK_SRC_DEFAULT;
    bus_config.glitch_ignore_cnt = 7;
    bus_config.flags.enable_internal_pullup = true;

    esp_err_t err = i2c_new_master_bus(&bus_config, &s_i2c_bus);
    if (err != ESP_OK) {
        ESP_LOGE(kTag, "OLED I2C bus failed: %s", esp_err_to_name(err));
        return false;
    }

    i2c_device_config_t device_config = {};
    device_config.dev_addr_length = I2C_ADDR_BIT_LEN_7;
    device_config.device_address = test_hardware::kOledAddress;
    device_config.scl_speed_hz = 400000;
    err = i2c_master_bus_add_device(s_i2c_bus, &device_config, &s_oled);
    if (err != ESP_OK) {
        ESP_LOGE(kTag, "OLED device failed: %s", esp_err_to_name(err));
        return false;
    }

    constexpr uint8_t init_commands[] = {
        0xAE,       // display off
        0xD5, 0x80, // clock divide
        0xA8, 0x3F, // multiplex: 64 rows
        0xD3, 0x00, // display offset
        0x40,       // start line 0
        0x8D, 0x14, // charge pump
        0x20, 0x00, // horizontal addressing mode
        0xA1,       // segment remap
        0xC8,       // COM scan direction
        0xDA, 0x12, // COM pins
        0x81, 0x7F, // contrast
        0xD9, 0xF1, // pre-charge
        0xDB, 0x40, // VCOMH
        0xA4,       // resume RAM display
        0xA6,       // normal display
        0xAF,       // display on
    };
    for (uint8_t command : init_commands) {
        if (oled_command(command) != ESP_OK) {
            ESP_LOGE(kTag, "OLED command failed: 0x%02X", command);
            return false;
        }
    }

    oled_pattern(false);
    ESP_LOGI(kTag, "OLED basic pattern written at 0x%02X", test_hardware::kOledAddress);
    return true;
}

bool camera_init() {
    camera_config_t config = {};
    config.ledc_channel = LEDC_CHANNEL_0;
    config.ledc_timer = LEDC_TIMER_0;
    config.pin_d0 = test_hardware::kCameraD0;
    config.pin_d1 = test_hardware::kCameraD1;
    config.pin_d2 = test_hardware::kCameraD2;
    config.pin_d3 = test_hardware::kCameraD3;
    config.pin_d4 = test_hardware::kCameraD4;
    config.pin_d5 = test_hardware::kCameraD5;
    config.pin_d6 = test_hardware::kCameraD6;
    config.pin_d7 = test_hardware::kCameraD7;
    config.pin_xclk = test_hardware::kCameraXclk;
    config.pin_pclk = test_hardware::kCameraPclk;
    config.pin_vsync = test_hardware::kCameraVsync;
    config.pin_href = test_hardware::kCameraHref;
    config.pin_sccb_sda = test_hardware::kCameraSccbSda;
    config.pin_sccb_scl = test_hardware::kCameraSccbScl;
    config.pin_pwdn = test_hardware::kCameraPwdn;
    config.pin_reset = test_hardware::kCameraReset;
    config.xclk_freq_hz = 20000000;
    config.pixel_format = PIXFORMAT_JPEG;
    config.frame_size = FRAMESIZE_QVGA;
    config.jpeg_quality = 12;
    config.fb_count = 2;
    config.grab_mode = CAMERA_GRAB_LATEST;
    config.fb_location = CAMERA_FB_IN_PSRAM;

    const esp_err_t err = esp_camera_init(&config);
    if (err != ESP_OK) {
        ESP_LOGE(kTag, "camera init failed: %s (0x%x)", esp_err_to_name(err), err);
        return false;
    }
    ESP_LOGI(kTag, "OV2640 camera initialized");
    return true;
}

void camera_capture_loop() {
    bool inverted = false;
    for (;;) {
        camera_fb_t* frame = esp_camera_fb_get();
        if (frame == nullptr) {
            ESP_LOGE(kTag, "camera capture failed");
        } else {
            ESP_LOGI(kTag, "camera frame: %ux%u format=%d bytes=%u", frame->width,
                     frame->height, frame->format, static_cast<unsigned>(frame->len));
            esp_camera_fb_return(frame);
        }
        if (s_oled != nullptr) {
            oled_pattern(inverted);
            inverted = !inverted;
        }
        vTaskDelay(pdMS_TO_TICKS(2000));
    }
}
}  // namespace

extern "C" void app_main() {
    ESP_LOGI(kTag, "starting component checks");
    const bool oled_ok = oled_init();
    const bool camera_ok = camera_init();
    ESP_LOGI(kTag, "check result: oled=%s camera=%s", oled_ok ? "PASS" : "FAIL",
             camera_ok ? "PASS" : "FAIL");

    if (camera_ok) {
        camera_capture_loop();
    } else {
        for (;;) {
            vTaskDelay(pdMS_TO_TICKS(2000));
        }
    }
}
