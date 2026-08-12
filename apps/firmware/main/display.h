#pragma once

#include <cstddef>
#include <cstdint>

namespace memora::display {

void init();
void show(const uint8_t* payload, std::size_t length);
void show(const char* text);

}  // namespace memora::display
