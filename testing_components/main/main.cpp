#include <algorithm>
#include <array>
#include <cmath>
#include <cstddef>
#include <cstdint>

#include "driver/i2c_master.h"
#include "driver/i2s_pdm.h"
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
i2s_chan_handle_t s_microphone = nullptr;

constexpr std::size_t kMicrophoneSampleCount = 512;

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

uint8_t oled_glyph_row(char character, int row) {
    // Five-by-seven bitmap font for the component-check label "memora".
    constexpr uint8_t kM[] = {0x00, 0x1A, 0x15, 0x15, 0x15, 0x15, 0x15};
    constexpr uint8_t kE[] = {0x0E, 0x11, 0x10, 0x1E, 0x10, 0x11, 0x0E};
    constexpr uint8_t kO[] = {0x0E, 0x11, 0x11, 0x11, 0x11, 0x11, 0x0E};
    constexpr uint8_t kR[] = {0x1E, 0x11, 0x11, 0x1E, 0x14, 0x12, 0x11};
    constexpr uint8_t kA[] = {0x0E, 0x11, 0x11, 0x1F, 0x11, 0x11, 0x11};
    constexpr uint8_t kG[] = {0x0E, 0x11, 0x10, 0x17, 0x11, 0x11, 0x0E};
    constexpr uint8_t kY[] = {0x11, 0x11, 0x0A, 0x04, 0x04, 0x04, 0x04};
    constexpr uint8_t kL[] = {0x10, 0x10, 0x10, 0x10, 0x10, 0x10, 0x1F};
    constexpr uint8_t kD[] = {0x1E, 0x11, 0x11, 0x11, 0x11, 0x11, 0x1E};
    constexpr uint8_t kI[] = {0x0E, 0x04, 0x04, 0x04, 0x04, 0x04, 0x0E};
    constexpr uint8_t kF[] = {0x1F, 0x10, 0x10, 0x1E, 0x10, 0x10, 0x10};
    constexpr uint8_t kQ[] = {0x0E, 0x11, 0x11, 0x11, 0x15, 0x12, 0x0D};
    constexpr uint8_t kU[] = {0x11, 0x11, 0x11, 0x11, 0x11, 0x11, 0x0E};
    constexpr uint8_t kT[] = {0x1F, 0x04, 0x04, 0x04, 0x04, 0x04, 0x04};
    constexpr uint8_t kW[] = {0x11, 0x11, 0x11, 0x15, 0x15, 0x15, 0x0A};
    constexpr uint8_t kN[] = {0x11, 0x19, 0x15, 0x15, 0x13, 0x13, 0x11};
    constexpr uint8_t kS[] = {0x0F, 0x10, 0x10, 0x0E, 0x01, 0x01, 0x1E};
    constexpr uint8_t kJ[] = {0x01, 0x01, 0x01, 0x01, 0x11, 0x11, 0x0E};
    constexpr uint8_t kTwo[] = {0x0E, 0x11, 0x01, 0x02, 0x04, 0x08, 0x1F};
    constexpr uint8_t kZero[] = {0x0E, 0x11, 0x13, 0x15, 0x19, 0x11, 0x0E};

    if (row < 0 || row >= 7) {
        return 0;
    }
    switch (character) {
        case 'm':
            return kM[row];
        case 'e':
            return kE[row];
        case 'o':
            return kO[row];
        case 'r':
            return kR[row];
        case 'a':
            return kA[row];
        case 'g':
            return kG[row];
        case 'y':
            return kY[row];
        case 'l':
            return kL[row];
        case 'd':
            return kD[row];
        case 'i':
            return kI[row];
        case 'f':
            return kF[row];
        case 'q':
            return kQ[row];
        case 'u':
            return kU[row];
        case 't':
            return kT[row];
        case 'w':
            return kW[row];
        case 'n':
            return kN[row];
        case 's':
            return kS[row];
        case 'j':
            return kJ[row];
        case '2':
            return kTwo[row];
        case '0':
            return kZero[row];
        default:
            return 0;
    }
}

void oled_text(const char* text) {
    std::array<uint8_t, kOledBufferSize> buffer{};
    // Native SSD1306 5x7 font size: one display pixel per bitmap pixel.
    constexpr int kScale = 1;
    constexpr int kGlyphWidth = 5;
    constexpr int kGlyphHeight = 7;
    constexpr int kGlyphSpacing = 1;
    constexpr int kLineSpacing = 1;
    constexpr int kMaxLines = 8;

    if (text == nullptr || *text == '\0') {
        return;
    }

    std::array<int, kMaxLines> line_lengths{};
    int line_count = 1;
    int current_line_length = 0;
    for (const char* cursor = text; *cursor != '\0'; ++cursor) {
        if (*cursor == '\n' && line_count < kMaxLines) {
            line_lengths[line_count - 1] = current_line_length;
            ++line_count;
            current_line_length = 0;
        } else {
            ++current_line_length;
        }
    }
    line_lengths[line_count - 1] = current_line_length;

    const int advance = (kGlyphWidth + kGlyphSpacing) * kScale;
    const int line_height = kGlyphHeight * kScale + kLineSpacing;
    const int origin_y = (kOledHeight - line_count * line_height + kLineSpacing) / 2;

    int line = 0;
    int column_index = 0;
    for (const char* cursor = text; *cursor != '\0'; ++cursor) {
        if (*cursor == '\n' && line + 1 < line_count) {
            ++line;
            column_index = 0;
            continue;
        }

        const int text_width = (line_lengths[line] * (kGlyphWidth + kGlyphSpacing) -
                                kGlyphSpacing) *
                               kScale;
        const int origin_x = (kOledWidth - text_width) / 2;
        const int character_x = origin_x + column_index * advance;
        for (int row = 0; row < kGlyphHeight; ++row) {
            const uint8_t glyph_bits = oled_glyph_row(*cursor, row);
            for (int column = 0; column < kGlyphWidth; ++column) {
                if ((glyph_bits & (1U << (kGlyphWidth - 1 - column))) == 0) {
                    continue;
                }
                for (int y = 0; y < kScale; ++y) {
                    for (int x = 0; x < kScale; ++x) {
                        const int pixel_x = character_x + column * kScale + x;
                        const int pixel_y = origin_y + line * line_height + row * kScale + y;
                        buffer[(pixel_y / 8) * kOledWidth + pixel_x] |=
                            static_cast<uint8_t>(1U << (pixel_y % 8));
                    }
                }
            }
        }
        ++column_index;
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

    oled_text("memora gerry\naldo rifqi gg\nauto win sini\nduit 20 juta");
    ESP_LOGI(kTag, "OLED test text written at 0x%02X", test_hardware::kOledAddress);
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

    sensor_t* sensor = esp_camera_sensor_get();
    if (sensor == nullptr || sensor->id.PID != OV3660_PID) {
        const unsigned pid = sensor == nullptr ? 0U : sensor->id.PID;
        ESP_LOGE(kTag, "unexpected camera sensor PID=0x%04x; expected OV3660 (0x%04x)",
                 pid, OV3660_PID);
        return false;
    }

    ESP_LOGI(kTag, "OV3660 camera initialized (PID=0x%04x)", sensor->id.PID);
    return true;
}

bool microphone_init() {
    i2s_chan_config_t channel_config = I2S_CHANNEL_DEFAULT_CONFIG(I2S_NUM_0, I2S_ROLE_MASTER);
    channel_config.dma_frame_num = kMicrophoneSampleCount;

    esp_err_t err = i2s_new_channel(&channel_config, nullptr, &s_microphone);
    if (err != ESP_OK) {
        ESP_LOGE(kTag, "microphone channel failed: %s", esp_err_to_name(err));
        return false;
    }

    i2s_pdm_rx_config_t pdm_config = {};
    pdm_config.clk_cfg = I2S_PDM_RX_CLK_DEFAULT_CONFIG(16000);
    pdm_config.slot_cfg = I2S_PDM_RX_SLOT_PCM_FMT_DEFAULT_CONFIG(
        I2S_DATA_BIT_WIDTH_16BIT, I2S_SLOT_MODE_MONO);
    pdm_config.gpio_cfg.clk = test_hardware::kMicrophoneClock;
    pdm_config.gpio_cfg.din = test_hardware::kMicrophoneData;
    pdm_config.gpio_cfg.invert_flags.clk_inv = false;

    err = i2s_channel_init_pdm_rx_mode(s_microphone, &pdm_config);
    if (err != ESP_OK) {
        ESP_LOGE(kTag, "microphone PDM init failed: %s", esp_err_to_name(err));
        return false;
    }

    err = i2s_channel_enable(s_microphone);
    if (err != ESP_OK) {
        ESP_LOGE(kTag, "microphone channel enable failed: %s", esp_err_to_name(err));
        return false;
    }

    ESP_LOGI(kTag, "PDM microphone initialized: CLK=GPIO%d DATA=GPIO%d rate=16kHz",
             test_hardware::kMicrophoneClock, test_hardware::kMicrophoneData);
    return true;
}

bool microphone_capture_test() {
    if (s_microphone == nullptr) {
        return false;
    }

    std::array<int16_t, kMicrophoneSampleCount> samples{};
    std::size_t bytes_read = 0;
    const esp_err_t err = i2s_channel_read(s_microphone, samples.data(), sizeof(samples),
                                           &bytes_read, 1000);
    if (err != ESP_OK || bytes_read == 0) {
        ESP_LOGE(kTag, "microphone read failed: %s bytes=%u", esp_err_to_name(err),
                 static_cast<unsigned>(bytes_read));
        return false;
    }

    const std::size_t sample_count = bytes_read / sizeof(samples[0]);
    int32_t peak = 0;
    int64_t absolute_sum = 0;
    for (std::size_t index = 0; index < sample_count; ++index) {
        const int32_t magnitude = std::abs(static_cast<int32_t>(samples[index]));
        peak = std::max(peak, magnitude);
        absolute_sum += magnitude;
    }

    ESP_LOGI(kTag, "microphone samples=%u peak=%ld avg_abs=%ld", static_cast<unsigned>(sample_count),
             static_cast<long>(peak), static_cast<long>(absolute_sum / sample_count));
    return true;
}

void component_capture_loop(bool camera_ok, bool microphone_ok) {
    for (;;) {
        if (camera_ok) {
            camera_fb_t* frame = esp_camera_fb_get();
            if (frame == nullptr) {
                ESP_LOGE(kTag, "camera capture failed");
            } else {
                ESP_LOGI(kTag, "camera frame: %ux%u format=%d bytes=%u", frame->width,
                         frame->height, frame->format, static_cast<unsigned>(frame->len));
                esp_camera_fb_return(frame);
            }
        } else {
            ESP_LOGW(kTag, "camera capture skipped because camera init failed");
        }
        if (microphone_ok) {
            microphone_capture_test();
        } else {
            ESP_LOGW(kTag, "microphone capture skipped because microphone init failed");
        }
        if (s_oled != nullptr) {
            oled_text("memora gerry\naldo rifqi gg\nauto win sini\nduit 20 juta");
        }
        vTaskDelay(pdMS_TO_TICKS(2000));
    }
}
}  // namespace

extern "C" void app_main() {
    ESP_LOGI(kTag, "starting component checks");
    const bool oled_ok = oled_init();
    const bool camera_ok = camera_init();
    const bool microphone_ok = microphone_init();
    ESP_LOGI(kTag, "check result: oled=%s camera=%s microphone=%s", oled_ok ? "PASS" : "FAIL",
             camera_ok ? "PASS" : "FAIL", microphone_ok ? "PASS" : "FAIL");

    if (camera_ok || microphone_ok) {
        component_capture_loop(camera_ok, microphone_ok);
    } else {
        for (;;) {
            vTaskDelay(pdMS_TO_TICKS(2000));
        }
    }
}
