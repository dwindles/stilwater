#pragma once
#include <windows.h>

namespace logging {
// Opens <dll folder>\logs\runtime.log, truncating the previous session.
void open(HMODULE self);
void write(const char* fmt, ...);
void close();
}  // namespace logging
