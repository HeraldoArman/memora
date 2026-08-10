#pragma once

#include <cstdint>

#include "driver/gpio.h"

namespace memora::hardware {

// User-provided wiring: OLED SDA -> D4/GPIO5, SCL -> D5/GPIO6.
constexpr gpio_num_t kOledSda = GPIO_NUM_5;
constexpr gpio_num_t kOledScl = GPIO_NUM_6;
constexpr uint8_t kOledAddress = 0x3C;

// User-provided wiring: switch between D1/GPIO2 and GND.
constexpr gpio_num_t kButton = GPIO_NUM_2;

// XIAO ESP32-S3 Sense OV2640 DVP camera wiring.
constexpr gpio_num_t kCameraXclk = GPIO_NUM_10;
constexpr gpio_num_t kCameraY2 = GPIO_NUM_15;
constexpr gpio_num_t kCameraY3 = GPIO_NUM_17;
constexpr gpio_num_t kCameraY4 = GPIO_NUM_18;
constexpr gpio_num_t kCameraY5 = GPIO_NUM_16;
constexpr gpio_num_t kCameraY6 = GPIO_NUM_14;
constexpr gpio_num_t kCameraY7 = GPIO_NUM_12;
constexpr gpio_num_t kCameraY8 = GPIO_NUM_11;
constexpr gpio_num_t kCameraY9 = GPIO_NUM_48;
constexpr gpio_num_t kCameraPclk = GPIO_NUM_13;
constexpr gpio_num_t kCameraVsync = GPIO_NUM_38;
constexpr gpio_num_t kCameraHref = GPIO_NUM_47;
constexpr gpio_num_t kCameraSda = GPIO_NUM_40;
constexpr gpio_num_t kCameraScl = GPIO_NUM_39;

// The onboard microphone is a PDM device on the Sense expansion board.
constexpr gpio_num_t kMicrophoneClock = GPIO_NUM_42;
constexpr gpio_num_t kMicrophoneData = GPIO_NUM_41;

}  // namespace memora::hardware
