#pragma once

namespace memora::jpeg {

// Initializes the OV3660 camera directly via esp_camera with PIXFORMAT_JPEG.
// PSRAM frame buffers, 640x480, quality 12. Does not use esp_capture —
// JPEG frames are sent via HTTP to the backend Video Bridge, not via LiveKit.
bool init();

// Spawns the capture+send FreeRTOS task (1 FPS).
void start();

// Stops the capture task.
void stop();

}  // namespace memora::jpeg