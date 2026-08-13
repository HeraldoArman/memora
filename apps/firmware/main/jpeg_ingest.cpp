#include "jpeg_ingest.h"

#include <algorithm>
#include <cstdio>
#include <cstring>

#include "driver/i2c_master.h"
#include "esp_camera.h"
#include "esp_crt_bundle.h"
#include "esp_http_client.h"
#include "esp_log.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

#include "hardware.h"

namespace {
constexpr char kTag[] = "memora-jpeg";
constexpr int kCaptureIntervalMs = 1000;
constexpr int kHttpPostTimeoutMs = 3000;
constexpr int kMaxJpegBytes = 600 * 1000;

static i2c_master_bus_handle_t s_camera_sccb_bus = nullptr;

static bool init_camera_sccb_bus() {
    i2c_master_bus_config_t bus_config = {};
    bus_config.i2c_port = memora::hardware::kCameraSccbI2cPort;
    bus_config.sda_io_num = memora::hardware::kCameraSda;
    bus_config.scl_io_num = memora::hardware::kCameraScl;
    bus_config.clk_source = I2C_CLK_SRC_DEFAULT;
    bus_config.glitch_ignore_cnt = 7;
    bus_config.flags.enable_internal_pullup = true;

    const esp_err_t err = i2c_new_master_bus(&bus_config, &s_camera_sccb_bus);
    if (err != ESP_OK) {
        ESP_LOGE(kTag, "camera SCCB bus init failed: %s", esp_err_to_name(err));
        return false;
    }
    ESP_LOGI(kTag, "camera SCCB bus ready on I2C port=%d SDA=%d SCL=%d",
             static_cast<int>(memora::hardware::kCameraSccbI2cPort),
             static_cast<int>(memora::hardware::kCameraSda),
             static_cast<int>(memora::hardware::kCameraScl));
    return true;
}

static camera_config_t make_camera_config() {
    camera_config_t config = {};
    config.ledc_channel = LEDC_CHANNEL_0;
    config.ledc_timer = LEDC_TIMER_0;
    config.pin_pwdn = -1;
    config.pin_reset = -1;
    config.pin_xclk = static_cast<int>(memora::hardware::kCameraXclk);
    // The OLED owns I2C port 1. Create the camera bus explicitly on port 0
    // above and tell esp32-camera to reuse it instead of installing its
    // default direct-pin SCCB bus (which is also port 1 in this build).
    config.pin_sccb_sda = -1;
    config.pin_sccb_scl = -1;
    config.pin_d0 = static_cast<int>(memora::hardware::kCameraY2);
    config.pin_d1 = static_cast<int>(memora::hardware::kCameraY3);
    config.pin_d2 = static_cast<int>(memora::hardware::kCameraY4);
    config.pin_d3 = static_cast<int>(memora::hardware::kCameraY5);
    config.pin_d4 = static_cast<int>(memora::hardware::kCameraY6);
    config.pin_d5 = static_cast<int>(memora::hardware::kCameraY7);
    config.pin_d6 = static_cast<int>(memora::hardware::kCameraY8);
    config.pin_d7 = static_cast<int>(memora::hardware::kCameraY9);
    config.pin_vsync = static_cast<int>(memora::hardware::kCameraVsync);
    config.pin_href = static_cast<int>(memora::hardware::kCameraHref);
    config.pin_pclk = static_cast<int>(memora::hardware::kCameraPclk);
    config.sccb_i2c_port = memora::hardware::kCameraSccbI2cPort;
    config.xclk_freq_hz = 10000000;
    config.frame_size = FRAMESIZE_XGA;
    config.pixel_format = PIXFORMAT_JPEG;
    config.jpeg_quality = 12;
    config.fb_count = 2;
    config.fb_location = CAMERA_FB_IN_PSRAM;
    config.grab_mode = CAMERA_GRAB_LATEST;
    return config;
}

static esp_err_t on_http_event(esp_http_client_event_t* event) {
    return ESP_OK;
}

static bool post_jpeg(const uint8_t* data, size_t len, int width, int height,
                      uint32_t frame_id) {
    if (len > static_cast<size_t>(kMaxJpegBytes)) {
        ESP_LOGW(kTag, "JPEG too large: %u bytes (max %d), skipping",
                 static_cast<unsigned>(len), kMaxJpegBytes);
        return false;
    }

    char frame_id_str[16];
    char time_str[16];
    char width_str[8];
    char height_str[8];
    snprintf(frame_id_str, sizeof(frame_id_str), "%lu", static_cast<unsigned long>(frame_id));
    snprintf(time_str, sizeof(time_str), "%llu",
             static_cast<unsigned long long>(esp_timer_get_time() / 1000));
    snprintf(width_str, sizeof(width_str), "%d", width);
    snprintf(height_str, sizeof(height_str), "%d", height);

    esp_http_client_config_t config = {};
    config.url = CONFIG_MEMORA_INGEST_URL;
    config.method = HTTP_METHOD_POST;
    config.timeout_ms = kHttpPostTimeoutMs;
    config.crt_bundle_attach = esp_crt_bundle_attach;
    config.event_handler = on_http_event;
    config.buffer_size = 512;
    config.buffer_size_tx = 4096;

    esp_http_client_handle_t client = esp_http_client_init(&config);
    if (client == nullptr) {
        ESP_LOGE(kTag, "HTTP client init failed");
        return false;
    }

    esp_http_client_set_header(client, "Content-Type", "image/jpeg");
    esp_http_client_set_header(client, "X-Memora-Device-ID",
                                CONFIG_MEMORA_LIVEKIT_IDENTITY);
    esp_http_client_set_header(client, "X-Frame-ID", frame_id_str);
    esp_http_client_set_header(client, "X-Capture-Time-Ms", time_str);
    esp_http_client_set_header(client, "X-Width", width_str);
    esp_http_client_set_header(client, "X-Height", height_str);
    esp_http_client_set_post_field(client, reinterpret_cast<const char*>(data), len);

    const esp_err_t err = esp_http_client_perform(client);
    const int status = esp_http_client_get_status_code(client);
    esp_http_client_cleanup(client);

    if (err != ESP_OK) {
        ESP_LOGW(kTag, "JPEG POST failed: %s", esp_err_to_name(err));
        return false;
    }
    if (status != 202) {
        ESP_LOGW(kTag, "JPEG POST rejected: HTTP %d", status);
        return false;
    }
    ESP_LOGI(kTag, "jpeg sent frame_id=%lu bytes=%u width=%d height=%d",
             static_cast<unsigned long>(frame_id), static_cast<unsigned>(len),
             width, height);
    return true;
}

static void capture_send_task(void*) {
    uint32_t frame_id = 0;
    for (;;) {
        camera_fb_t* fb = esp_camera_fb_get();
        if (fb == nullptr) {
            ESP_LOGW(kTag, "camera fb get failed");
            vTaskDelay(pdMS_TO_TICKS(kCaptureIntervalMs));
            continue;
        }
        if (fb->format == PIXFORMAT_JPEG) {
            ++frame_id;
            post_jpeg(fb->buf, fb->len, fb->width, fb->height, frame_id);
        } else {
            ESP_LOGW(kTag, "unexpected format: %d", fb->format);
        }
        esp_camera_fb_return(fb);
        vTaskDelay(pdMS_TO_TICKS(kCaptureIntervalMs));
    }
}

static TaskHandle_t s_task = nullptr;
}  // namespace

namespace memora::jpeg {

bool init() {
    if (!init_camera_sccb_bus()) {
        return false;
    }

    auto config = make_camera_config();
    const esp_err_t err = esp_camera_init(&config);
    if (err != ESP_OK) {
        ESP_LOGE(kTag, "esp_camera_init failed: %s", esp_err_to_name(err));
        return false;
    }

    sensor_t* sensor = esp_camera_sensor_get();
    if (sensor == nullptr || sensor->set_hmirror == nullptr || sensor->set_vflip == nullptr) {
        ESP_LOGE(kTag, "OV3660 orientation controls are unavailable");
        esp_camera_deinit();
        return false;
    }
    const int mirror_result = sensor->set_hmirror(sensor, 1);
    const int flip_result = sensor->set_vflip(sensor, 1);
    if (mirror_result != 0 || flip_result != 0) {
        ESP_LOGE(kTag, "OV3660 180-degree rotation failed: mirror=%d flip=%d",
                 mirror_result, flip_result);
        esp_camera_deinit();
        return false;
    }
    ESP_LOGI(kTag, "OV3660 JPEG camera ready: 1024x768 quality=12 PSRAM");
    ESP_LOGI(kTag, "OV3660 image rotated 180 degrees (hmirror=1, vflip=1)");
    return true;
}

void start() {
    if (s_task != nullptr) return;
    xTaskCreate(capture_send_task, "jpeg_ingest", 8192, nullptr, 5, &s_task);
    ESP_LOGI(kTag, "JPEG capture+send task started (1 FPS → %s)", CONFIG_MEMORA_INGEST_URL);
}

void stop() {
    if (s_task != nullptr) {
        vTaskDelete(s_task);
        s_task = nullptr;
    }
}

}  // namespace memora::jpeg
