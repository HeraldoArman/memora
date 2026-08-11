#pragma once

#include "esp_capture.h"

namespace memora::media {

// Initializes the OV3660 DVP camera and onboard PDM microphone capture sources.
bool init();

// Returns the capture graph consumed by the LiveKit media publisher.
esp_capture_handle_t capture();

}  // namespace memora::media
