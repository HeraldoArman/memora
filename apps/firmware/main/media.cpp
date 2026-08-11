#include "media.h"

#include <algorithm>
#include <cstddef>
#include <cstdint>
#include <cstring>

#include "driver/i2c_master.h"
#include "driver/i2s_pdm.h"
#include "esp_log.h"
#include "esp_capture.h"
#include "esp_capture_types.h"
#include "impl/esp_capture_video_dvp_src.h"
#include "freertos/FreeRTOS.h"

#include "hardware.h"

namespace {
constexpr char kTag[] = "memora-media";
constexpr uint32_t kMicrophoneSampleRate = 16000;
constexpr std::size_t kMicrophoneDmaSamples = 320;

struct PdmMicrophoneSource {
    esp_capture_audio_src_if_t base = {};
    i2s_chan_handle_t channel = nullptr;
    esp_capture_audio_info_t info = {
        .format_id = ESP_CAPTURE_FMT_ID_PCM,
        .sample_rate = kMicrophoneSampleRate,
        .channel = 1,
        .bits_per_sample = 16,
    };
    uint64_t samples_read = 0;
    uint32_t frame_count = 0;
    bool started = false;
};

i2c_master_bus_handle_t s_camera_sccb_bus = nullptr;
PdmMicrophoneSource s_microphone;
esp_capture_video_src_if_t* s_camera = nullptr;
esp_capture_handle_t s_capture = nullptr;

PdmMicrophoneSource* microphone_from_base(esp_capture_audio_src_if_t* base) {
    return reinterpret_cast<PdmMicrophoneSource*>(base);
}

esp_capture_err_t microphone_open(esp_capture_audio_src_if_t*) {
    return ESP_CAPTURE_ERR_OK;
}

esp_capture_err_t microphone_codecs(esp_capture_audio_src_if_t*,
                                    const esp_capture_format_id_t** codecs, uint8_t* count) {
    static const esp_capture_format_id_t kCodecs[] = {ESP_CAPTURE_FMT_ID_PCM};
    *codecs = kCodecs;
    *count = 1;
    return ESP_CAPTURE_ERR_OK;
}

esp_capture_err_t microphone_set_caps(esp_capture_audio_src_if_t* base,
                                      const esp_capture_audio_info_t* caps) {
    if (caps == nullptr || caps->format_id != ESP_CAPTURE_FMT_ID_PCM || caps->channel != 1 ||
        caps->bits_per_sample != 16) {
        return ESP_CAPTURE_ERR_NOT_SUPPORTED;
    }
    microphone_from_base(base)->info = *caps;
    return ESP_CAPTURE_ERR_OK;
}

esp_capture_err_t microphone_negotiate(esp_capture_audio_src_if_t* base,
                                       esp_capture_audio_info_t* input,
                                       esp_capture_audio_info_t* output) {
    if (input == nullptr || output == nullptr) {
        return ESP_CAPTURE_ERR_INVALID_ARG;
    }
    if (input->format_id != ESP_CAPTURE_FMT_ID_PCM && input->format_id != ESP_CAPTURE_FMT_ID_ANY) {
        return ESP_CAPTURE_ERR_NOT_SUPPORTED;
    }
    PdmMicrophoneSource* source = microphone_from_base(base);
    if (input->format_id == ESP_CAPTURE_FMT_ID_PCM && input->sample_rate != kMicrophoneSampleRate) {
        return ESP_CAPTURE_ERR_NOT_SUPPORTED;
    }
    *output = source->info;
    return ESP_CAPTURE_ERR_OK;
}

esp_capture_err_t microphone_start(esp_capture_audio_src_if_t* base) {
    PdmMicrophoneSource* source = microphone_from_base(base);
    if (source->channel == nullptr) {
        return ESP_CAPTURE_ERR_INVALID_STATE;
    }
    const esp_err_t err = i2s_channel_enable(source->channel);
    if (err != ESP_OK && err != ESP_ERR_INVALID_STATE) {
        ESP_LOGE(kTag, "PDM microphone start failed: %s", esp_err_to_name(err));
        return ESP_CAPTURE_ERR_INTERNAL;
    }
    source->samples_read = 0;
    source->frame_count = 0;
    source->started = true;
    ESP_LOGI(kTag, "PDM microphone started: GPIO%d clock, GPIO%d data, %lu Hz",
             memora::hardware::kMicrophoneClock, memora::hardware::kMicrophoneData,
             static_cast<unsigned long>(source->info.sample_rate));
    return ESP_CAPTURE_ERR_OK;
}

esp_capture_err_t microphone_read(esp_capture_audio_src_if_t* base,
                                  esp_capture_stream_frame_t* frame) {
    PdmMicrophoneSource* source = microphone_from_base(base);
    if (!source->started || frame == nullptr || frame->data == nullptr || frame->size <= 0) {
        return ESP_CAPTURE_ERR_INVALID_ARG;
    }

    std::size_t bytes_read = 0;
    const esp_err_t err = i2s_channel_read(source->channel, frame->data, frame->size, &bytes_read,
                                           1000);
    if (err != ESP_OK || bytes_read == 0) {
        ESP_LOGE(kTag, "PDM microphone read failed: %s", esp_err_to_name(err));
        return ESP_CAPTURE_ERR_INTERNAL;
    }

    frame->size = static_cast<int>(bytes_read);
    frame->pts = static_cast<uint32_t>(source->samples_read * 1000 / source->info.sample_rate);
    source->samples_read += bytes_read / (source->info.bits_per_sample / 8);
    ++source->frame_count;

    if (source->frame_count % 50 == 0) {
        const auto* samples = reinterpret_cast<const int16_t*>(frame->data);
        const std::size_t sample_count = bytes_read / sizeof(int16_t);
        int32_t peak = 0;
        int64_t absolute_sum = 0;
        for (std::size_t index = 0; index < sample_count; ++index) {
            const int32_t value = samples[index];
            const int32_t magnitude = value < 0 ? -value : value;
            peak = std::max(peak, magnitude);
            absolute_sum += magnitude;
        }
        ESP_LOGI(kTag, "microphone frame=%lu samples=%u peak=%ld avg_abs=%ld",
                 static_cast<unsigned long>(source->frame_count),
                 static_cast<unsigned>(sample_count), static_cast<long>(peak),
                 static_cast<long>(sample_count == 0 ? 0 : absolute_sum / sample_count));
    }
    return ESP_CAPTURE_ERR_OK;
}

esp_capture_err_t microphone_stop(esp_capture_audio_src_if_t* base) {
    PdmMicrophoneSource* source = microphone_from_base(base);
    if (source->started) {
        i2s_channel_disable(source->channel);
    }
    source->started = false;
    return ESP_CAPTURE_ERR_OK;
}

esp_capture_err_t microphone_close(esp_capture_audio_src_if_t*) {
    return ESP_CAPTURE_ERR_OK;
}

esp_capture_err_t capture_event(esp_capture_event_t event, void*) {
    ESP_LOGI(kTag, "capture event=%d", static_cast<int>(event));
    return ESP_CAPTURE_ERR_OK;
}

bool init_camera_sccb_bus() {
    i2c_master_bus_config_t bus_config = {};
    bus_config.i2c_port = memora::hardware::kCameraSccbI2cPort;
    bus_config.sda_io_num = memora::hardware::kCameraSda;
    bus_config.scl_io_num = memora::hardware::kCameraScl;
    bus_config.clk_source = I2C_CLK_SRC_DEFAULT;
    bus_config.glitch_ignore_cnt = 7;
    bus_config.flags.enable_internal_pullup = true;

    const esp_err_t err = i2c_new_master_bus(&bus_config, &s_camera_sccb_bus);
    if (err != ESP_OK) {
        ESP_LOGE(kTag, "camera SCCB bus failed: %s", esp_err_to_name(err));
        return false;
    }
    return true;
}

bool init_microphone() {
    s_microphone.base.open = microphone_open;
    s_microphone.base.get_support_codecs = microphone_codecs;
    s_microphone.base.set_fixed_caps = microphone_set_caps;
    s_microphone.base.negotiate_caps = microphone_negotiate;
    s_microphone.base.start = microphone_start;
    s_microphone.base.read_frame = microphone_read;
    s_microphone.base.stop = microphone_stop;
    s_microphone.base.close = microphone_close;

    i2s_chan_config_t channel_config =
        I2S_CHANNEL_DEFAULT_CONFIG(I2S_NUM_0, I2S_ROLE_MASTER);
    channel_config.dma_desc_num = 6;
    channel_config.dma_frame_num = kMicrophoneDmaSamples;
    esp_err_t err = i2s_new_channel(&channel_config, nullptr, &s_microphone.channel);
    if (err != ESP_OK) {
        ESP_LOGE(kTag, "microphone channel allocation failed: %s", esp_err_to_name(err));
        return false;
    }

    i2s_pdm_rx_config_t pdm_config = {};
    pdm_config.clk_cfg = I2S_PDM_RX_CLK_DEFAULT_CONFIG(kMicrophoneSampleRate);
    pdm_config.slot_cfg = I2S_PDM_RX_SLOT_PCM_FMT_DEFAULT_CONFIG(
        I2S_DATA_BIT_WIDTH_16BIT, I2S_SLOT_MODE_MONO);
    pdm_config.gpio_cfg.clk = memora::hardware::kMicrophoneClock;
    pdm_config.gpio_cfg.din = memora::hardware::kMicrophoneData;
    pdm_config.gpio_cfg.invert_flags.clk_inv = false;

    err = i2s_channel_init_pdm_rx_mode(s_microphone.channel, &pdm_config);
    if (err != ESP_OK) {
        ESP_LOGE(kTag, "microphone PDM configuration failed: %s", esp_err_to_name(err));
        return false;
    }
    return true;
}
}  // namespace

namespace memora::media {

bool init() {
    if (!init_camera_sccb_bus() || !init_microphone()) {
        return false;
    }

    esp_capture_video_dvp_src_cfg_t camera_config = {};
    camera_config.buf_count = 2;
    camera_config.pwr_pin = -1;
    camera_config.reset_pin = -1;
    camera_config.xclk_pin = memora::hardware::kCameraXclk;
    camera_config.data[0] = memora::hardware::kCameraY2;
    camera_config.data[1] = memora::hardware::kCameraY3;
    camera_config.data[2] = memora::hardware::kCameraY4;
    camera_config.data[3] = memora::hardware::kCameraY5;
    camera_config.data[4] = memora::hardware::kCameraY6;
    camera_config.data[5] = memora::hardware::kCameraY7;
    camera_config.data[6] = memora::hardware::kCameraY8;
    camera_config.data[7] = memora::hardware::kCameraY9;
    camera_config.vsync_pin = memora::hardware::kCameraVsync;
    camera_config.href_pin = memora::hardware::kCameraHref;
    camera_config.pclk_pin = memora::hardware::kCameraPclk;
    camera_config.xclk_freq = 20000000;
    camera_config.i2c_port = memora::hardware::kCameraSccbI2cPort;
    s_camera = esp_capture_new_video_dvp_src(&camera_config);
    if (s_camera == nullptr) {
        ESP_LOGE(kTag, "OV3660 DVP source allocation failed");
        return false;
    }

    esp_capture_cfg_t capture_config = {};
    capture_config.sync_mode = ESP_CAPTURE_SYNC_MODE_SYSTEM;
    capture_config.audio_src = &s_microphone.base;
    capture_config.video_src = s_camera;
    const esp_capture_err_t err = esp_capture_open(&capture_config, &s_capture);
    if (err != ESP_CAPTURE_ERR_OK) {
        ESP_LOGE(kTag, "capture graph open failed: %d", static_cast<int>(err));
        return false;
    }
    esp_capture_set_event_cb(s_capture, capture_event, nullptr);
    ESP_LOGI(kTag, "OV3660 camera + PDM microphone capture graph ready");
    return true;
}

esp_capture_handle_t capture() {
    return s_capture;
}

}  // namespace memora::media
