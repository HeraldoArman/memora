#pragma once

#include "driver/gpio.h"

namespace test_hardware {

// OLED: VCC -> 3V3, GND -> GND, SDA -> D4/GPIO5, SCL -> D5/GPIO6.
constexpr gpio_num_t kOledSda = GPIO_NUM_5;
constexpr gpio_num_t kOledScl = GPIO_NUM_6;
constexpr uint8_t kOledAddress = 0x3C;

// XIAO ESP32-S3 Sense OV3660 DVP camera pins.
constexpr int kCameraPwdn = -1;
constexpr int kCameraReset = -1;
constexpr int kCameraXclk = 10;
constexpr int kCameraSccbSda = 40;
constexpr int kCameraSccbScl = 39;
constexpr int kCameraD0 = 15;
constexpr int kCameraD1 = 17;
constexpr int kCameraD2 = 18;
constexpr int kCameraD3 = 16;
constexpr int kCameraD4 = 14;
constexpr int kCameraD5 = 12;
constexpr int kCameraD6 = 11;
constexpr int kCameraD7 = 48;
constexpr int kCameraVsync = 38;
constexpr int kCameraHref = 47;
constexpr int kCameraPclk = 13;

// XIAO ESP32-S3 Sense onboard PDM microphone pins.
constexpr gpio_num_t kMicrophoneClock = GPIO_NUM_42;
constexpr gpio_num_t kMicrophoneData = GPIO_NUM_41;

}  // namespace test_hardware
