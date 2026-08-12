#include "display.h"

#include <algorithm>
#include <array>
#include <cstddef>
#include <cstdint>
#include <cstring>

#include "driver/i2c_master.h"
#include "esp_log.h"

#include "hardware.h"

namespace {
constexpr char kTag[] = "memora-display";
constexpr int kWidth = 128;
constexpr int kHeight = 64;
constexpr int kGlyphWidth = 5;
constexpr int kGlyphHeight = 7;
constexpr int kGlyphSpacing = 1;
constexpr int kLineHeight = 8;
constexpr int kMaxColumns = kWidth / (kGlyphWidth + kGlyphSpacing);
constexpr int kMaxLines = kHeight / kLineHeight;
constexpr std::size_t kBufferSize = kWidth * kHeight / 8;

i2c_master_bus_handle_t s_bus = nullptr;
i2c_master_dev_handle_t s_oled = nullptr;

std::array<uint8_t, kGlyphHeight> glyph(char character) {
    // Native 5x7 font. The renderer accepts lowercase, uppercase, digits, and
    // common punctuation used by the backend's display messages.
    constexpr std::array<uint8_t, kGlyphHeight> kSpace = {0, 0, 0, 0, 0, 0, 0};
    constexpr std::array<uint8_t, kGlyphHeight> kQuestion = {0x0E, 0x11, 0x02, 0x04, 0x04, 0x00,
                                                               0x04};
    constexpr std::array<uint8_t, kGlyphHeight> kLetters[] = {
        {0x00, 0x0E, 0x01, 0x0F, 0x11, 0x0F, 0x00}, // a
        {0x10, 0x10, 0x1E, 0x11, 0x11, 0x1E, 0x00}, // b
        {0x00, 0x00, 0x0E, 0x10, 0x10, 0x0E, 0x00}, // c
        {0x01, 0x01, 0x0F, 0x11, 0x11, 0x0F, 0x00}, // d
        {0x00, 0x0E, 0x11, 0x1F, 0x10, 0x0E, 0x00}, // e
        {0x06, 0x09, 0x08, 0x1C, 0x08, 0x08, 0x00}, // f
        {0x00, 0x0F, 0x11, 0x0F, 0x01, 0x0E, 0x00}, // g
        {0x10, 0x10, 0x1E, 0x11, 0x11, 0x11, 0x00}, // h
        {0x04, 0x00, 0x0C, 0x04, 0x04, 0x0E, 0x00}, // i
        {0x02, 0x00, 0x06, 0x02, 0x12, 0x0C, 0x00}, // j
        {0x10, 0x10, 0x12, 0x1C, 0x12, 0x11, 0x00}, // k
        {0x0C, 0x04, 0x04, 0x04, 0x04, 0x0E, 0x00}, // l
        {0x00, 0x00, 0x1A, 0x15, 0x15, 0x15, 0x00}, // m
        {0x00, 0x00, 0x1E, 0x11, 0x11, 0x11, 0x00}, // n
        {0x00, 0x00, 0x0E, 0x11, 0x11, 0x0E, 0x00}, // o
        {0x00, 0x00, 0x1E, 0x11, 0x1E, 0x10, 0x10}, // p
        {0x00, 0x00, 0x0F, 0x11, 0x0F, 0x01, 0x01}, // q
        {0x00, 0x00, 0x16, 0x19, 0x10, 0x10, 0x00}, // r
        {0x00, 0x00, 0x0F, 0x10, 0x0E, 0x1E, 0x00}, // s
        {0x08, 0x08, 0x1C, 0x08, 0x09, 0x06, 0x00}, // t
        {0x00, 0x00, 0x11, 0x11, 0x11, 0x0F, 0x00}, // u
        {0x00, 0x00, 0x11, 0x11, 0x0A, 0x04, 0x00}, // v
        {0x00, 0x00, 0x11, 0x15, 0x15, 0x0A, 0x00}, // w
        {0x00, 0x00, 0x11, 0x0A, 0x04, 0x0A, 0x11}, // x
        {0x00, 0x00, 0x11, 0x0F, 0x01, 0x0E, 0x00}, // y
        {0x00, 0x00, 0x1F, 0x02, 0x04, 0x1F, 0x00}, // z
    };
    constexpr std::array<uint8_t, kGlyphHeight> kDigits[] = {
        {0x0E, 0x11, 0x13, 0x15, 0x19, 0x11, 0x0E}, // 0
        {0x04, 0x0C, 0x04, 0x04, 0x04, 0x04, 0x0E}, // 1
        {0x0E, 0x11, 0x01, 0x02, 0x04, 0x08, 0x1F}, // 2
        {0x1E, 0x01, 0x01, 0x0E, 0x01, 0x01, 0x1E}, // 3
        {0x02, 0x06, 0x0A, 0x12, 0x1F, 0x02, 0x02}, // 4
        {0x1F, 0x10, 0x10, 0x1E, 0x01, 0x01, 0x1E}, // 5
        {0x06, 0x08, 0x10, 0x1E, 0x11, 0x11, 0x0E}, // 6
        {0x1F, 0x01, 0x02, 0x04, 0x08, 0x08, 0x08}, // 7
        {0x0E, 0x11, 0x11, 0x0E, 0x11, 0x11, 0x0E}, // 8
        {0x0E, 0x11, 0x11, 0x0F, 0x01, 0x02, 0x0C}, // 9
    };

    if (character >= 'A' && character <= 'Z') {
        character = static_cast<char>(character - 'A' + 'a');
    }
    if (character >= 'a' && character <= 'z') {
        return kLetters[character - 'a'];
    }
    if (character >= '0' && character <= '9') {
        return kDigits[character - '0'];
    }
    if (character == ' ') {
        return kSpace;
    }
    if (character == '.') {
        return {0, 0, 0, 0, 0, 0x06, 0x06};
    }
    if (character == '!') {
        return {0x04, 0x04, 0x04, 0x04, 0x04, 0x00, 0x04};
    }
    if (character == ':') {
        return {0, 0x06, 0x06, 0, 0x06, 0x06, 0};
    }
    if (character == '-') {
        return {0, 0, 0, 0x1F, 0, 0, 0};
    }
    return kQuestion;
}

void write_command(uint8_t command) {
    if (s_oled == nullptr) {
        return;
    }
    const uint8_t packet[] = {0x00, command};
    const esp_err_t err = i2c_master_transmit(s_oled, packet, sizeof(packet), 100);
    if (err != ESP_OK) {
        ESP_LOGW(kTag, "OLED command 0x%02X failed: %s", command, esp_err_to_name(err));
    }
}

void write_data(const uint8_t* data, std::size_t length) {
    std::array<uint8_t, 17> packet{};
    packet[0] = 0x40;
    while (length > 0) {
        const std::size_t chunk = std::min<std::size_t>(length, packet.size() - 1);
        std::copy(data, data + chunk, packet.begin() + 1);
        const esp_err_t err = i2c_master_transmit(s_oled, packet.data(), chunk + 1, 100);
        if (err != ESP_OK) {
            ESP_LOGW(kTag, "OLED data transfer failed: %s", esp_err_to_name(err));
            return;
        }
        data += chunk;
        length -= chunk;
    }
}

void render_text(const uint8_t* payload, std::size_t length) {
    std::array<uint8_t, kBufferSize> buffer{};
    std::array<std::array<char, kMaxColumns>, kMaxLines> lines{};
    std::array<int, kMaxLines> line_lengths{};
    int line = 0;
    int column = 0;

    for (std::size_t index = 0; index < length && line < kMaxLines; ++index) {
        const char character = static_cast<char>(payload[index]);
        if (character == '\r') {
            continue;
        }
        if (character == '\n' || column == kMaxColumns) {
            ++line;
            column = 0;
            if (line == kMaxLines) {
                break;
            }
            if (character == '\n') {
                continue;
            }
        }
        lines[line][column++] = character;
        line_lengths[line] = column;
    }

    const int line_count = std::max(1, std::min(kMaxLines, line + 1));
    const int origin_y = (kHeight - line_count * kLineHeight + 1) / 2;
    for (int current_line = 0; current_line < line_count; ++current_line) {
        const int text_width = line_lengths[current_line] == 0
                                   ? 0
                                   : line_lengths[current_line] * (kGlyphWidth + kGlyphSpacing) -
                                         kGlyphSpacing;
        const int origin_x = (kWidth - text_width) / 2;
        for (int character_index = 0; character_index < line_lengths[current_line];
             ++character_index) {
            const auto rows = glyph(lines[current_line][character_index]);
            for (int row = 0; row < kGlyphHeight; ++row) {
                for (int column_index = 0; column_index < kGlyphWidth; ++column_index) {
                    if ((rows[row] & (1U << (kGlyphWidth - 1 - column_index))) == 0) {
                        continue;
                    }
                    const int pixel_x = origin_x + character_index * (kGlyphWidth + kGlyphSpacing) +
                                        column_index;
                    const int pixel_y = origin_y + current_line * kLineHeight + row;
                    buffer[(pixel_y / 8) * kWidth + pixel_x] |=
                        static_cast<uint8_t>(1U << (pixel_y % 8));
                }
            }
        }
    }

    for (uint8_t page = 0; page < kHeight / 8; ++page) {
        write_command(static_cast<uint8_t>(0xB0 | page));
        write_command(0x00);
        write_command(0x10);
        write_data(buffer.data() + page * kWidth, kWidth);
    }
}
}  // namespace

namespace memora::display {

void init() {
    i2c_master_bus_config_t bus_config = {};
    bus_config.i2c_port = hardware::kOledI2cPort;
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

    constexpr uint8_t commands[] = {0xAE, 0xD5, 0x80, 0xA8, 0x3F, 0xD3, 0x00,
                                    0x40, 0x8D, 0x14, 0x20, 0x00, 0xA1, 0xC8,
                                    0xDA, 0x12, 0x81, 0x7F, 0xD9, 0xF1, 0xDB,
                                    0x40, 0xA4, 0xA6, 0xAF};
    for (uint8_t command : commands) {
        write_command(command);
    }
    ESP_LOGI(kTag, "OLED ready on SDA=%d SCL=%d I2C port=%d", hardware::kOledSda,
             hardware::kOledScl, hardware::kOledI2cPort);
}

void show(const uint8_t* payload, std::size_t length) {
    if (s_oled == nullptr || payload == nullptr || length == 0) {
        return;
    }
    const std::size_t preview_length = std::min<std::size_t>(length, 120);
    ESP_LOGI(kTag, "display <- len=%u text=%.*s", static_cast<unsigned>(length),
             static_cast<int>(preview_length), reinterpret_cast<const char*>(payload));
    render_text(payload, length);
}

void show(const char* text) {
    if (text != nullptr) {
        show(reinterpret_cast<const uint8_t*>(text), std::strlen(text));
    }
}

}  // namespace memora::display
