#include "log.h"

#include <cstdarg>
#include <cstdio>
#include <filesystem>
#include <mutex>

namespace {
std::FILE* g_file = nullptr;
std::mutex g_mutex;
}  // namespace

namespace logging {

void open(HMODULE self) {
  wchar_t path[MAX_PATH];
  GetModuleFileNameW(self, path, MAX_PATH);
  auto dir = std::filesystem::path(path).parent_path() / L"logs";
  std::error_code ec;
  std::filesystem::create_directories(dir, ec);
  g_file = _wfsopen((dir / L"runtime.log").c_str(), L"w", _SH_DENYWR);
}

void write(const char* fmt, ...) {
  if (!g_file) return;
  std::lock_guard lock(g_mutex);
  SYSTEMTIME t;
  GetLocalTime(&t);
  std::fprintf(g_file, "[%02d:%02d:%02d.%03d] ", t.wHour, t.wMinute, t.wSecond, t.wMilliseconds);
  va_list args;
  va_start(args, fmt);
  std::vfprintf(g_file, fmt, args);
  va_end(args);
  std::fputc('\n', g_file);
  std::fflush(g_file);
}

void close() {
  if (g_file) std::fclose(g_file);
  g_file = nullptr;
}

}  // namespace logging
