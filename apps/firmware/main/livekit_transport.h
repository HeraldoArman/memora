#pragma once

namespace memora::livekit {

bool init();
bool connect();
void publish_telemetry(bool button_pressed);

}  // namespace memora::livekit
