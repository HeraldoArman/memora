#pragma once

namespace memora::button {

using PressCallback = void (*)();

void init(PressCallback callback);

}  // namespace memora::button
